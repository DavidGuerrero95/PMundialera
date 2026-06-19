from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from mundialera.domain.models import (
    EvidenceCategory,
    EvidenceItem,
    Prediction,
    PredictionCalibration,
    PredictionOutcome,
    PredictionRecord,
    ProbabilityProfile,
    ResearchBrief,
    ResearchRecord,
    Scoreline,
    SourceTier,
    SubmissionResult,
)
from mundialera.domain.ports import PredictionHistory, PredictionRecorder, ResearchRecorder

SCHEMA_VERSION = 3


ANALYSIS_DIMENSION_TERMS: dict[str, tuple[str, ...]] = {
    "equipos": ("team", "equipo", "seleccion", "squad", "plantel"),
    "torneo": ("mundial", "grupo", "tabla", "puntos", "diferencia de gol"),
    "jugadores": ("jugador", "player", "capitan", "figura", "delantero", "mediocampista"),
    "jugadores_diferenciables": ("estrella", "diferencial", "key player", "jugador clave"),
    "jugadores_estrellas_desequilibrantes": (
        "estrella",
        "desequilibrante",
        "desequilibrio",
        "differencemaker",
        "game changer",
        "key player",
        "jugador clave",
        "figura",
    ),
    "arbitros": ("arbitro", "referee"),
    "faltas_tarjetas": ("falta", "tarjeta", "cards", "disciplina", "penal"),
    "hinchada": ("hinchada", "aficion", "fans", "supporters", "localia"),
    "sede_cancha_clima": ("estadio", "sede", "venue", "clima", "cancha", "humidity", "calor"),
    "titularidad": ("titular", "alineacion", "starting", "lineup", "xi"),
    "suplencia": ("suplente", "bench", "rotacion", "substitute"),
    "lesionados_sancionados_convocados": (
        "lesion",
        "injury",
        "sancionado",
        "suspended",
        "convocado",
        "call-up",
        "baja",
    ),
    "buen_ritmo": ("buen ritmo", "high tempo", "presion", "intensidad", "ataque fluido"),
    "mal_ritmo": ("mal ritmo", "low tempo", "lento", "bloque bajo", "marcador corto"),
    "buen_ataque": ("buen ataque", "techo ofensivo", "xg", "tiros", "goles esperados"),
    "mal_ataque": ("mal ataque", "baja conversion", "pocos tiros", "sin gol"),
    "buena_defensa": ("buena defensa", "clean sheet", "portero", "atajadas", "resiliencia"),
    "mala_defensa": (
        "mala defensa",
        "fragilidad defensiva",
        "concede",
        "leaky",
        "bajas defensivas",
    ),
}


class SqlitePredictionStore(PredictionRecorder, ResearchRecorder, PredictionHistory):
    def __init__(self, base_dir: Path, *, timezone_name: str) -> None:
        self._base_dir = base_dir
        self._timezone = ZoneInfo(timezone_name)
        self._database_path = base_dir / "pmundialera.sqlite3"
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @property
    def database_path(self) -> Path:
        return self._database_path

    def record_prediction(
        self,
        prediction: Prediction,
        submission: SubmissionResult,
    ) -> None:
        match = prediction.match
        record = PredictionRecord(
            record_id=str(uuid.uuid4()),
            created_at=datetime.now(self._timezone),
            group=match.group or "",
            match_id=match.match_id,
            match_label=match.label,
            kickoff=match.kickoff,
            primary=prediction.primary,
            hedge=prediction.hedge,
            submitted_scoreline=submission.scoreline,
            confidence=prediction.confidence,
            rationale=prediction.rationale,
            submitted=submission.submitted,
            dry_run=submission.dry_run,
            submission_message=submission.message,
            probabilities=prediction.probabilities,
            decision_flags=prediction.decision_flags,
        )
        with self._connect() as connection:
            self._insert_prediction(connection, record)

    def record_research_brief(self, brief: ResearchBrief) -> None:
        match = brief.match
        record = ResearchRecord(
            record_id=str(uuid.uuid4()),
            created_at=datetime.now(self._timezone),
            group=match.group or "",
            match_id=match.match_id,
            match_label=match.label,
            kickoff=match.kickoff,
            home_team=match.home.name,
            away_team=match.away.name,
            evidence=brief.evidence,
            structured_evidence=brief.structured_evidence,
            uncertainty=brief.uncertainty,
            calibration=brief.calibration,
            probabilities=brief.probability_profile,
            analysis_dimensions=_analysis_dimensions_from_brief(brief),
            star_player_signals=_star_player_signals_from_brief(brief),
        )
        with self._connect() as connection:
            self._insert_research_record(connection, record)

    def record_outcomes(self, outcomes: list[PredictionOutcome]) -> int:
        with self._connect() as connection:
            before = connection.total_changes
            for outcome in outcomes:
                self._insert_outcome(connection, outcome)
            return connection.total_changes - before

    def load_prediction_records(self) -> list[PredictionRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT record_id, created_at, group_name, match_id, match_label, kickoff,
                       primary_home, primary_away, hedge_home, hedge_away,
                       submitted_home, submitted_away, confidence, rationale_json,
                       submitted, dry_run, submission_message, probabilities_json,
                       decision_flags_json
                FROM predictions
                ORDER BY created_at ASC, rowid ASC
                """
            ).fetchall()
        return [_record_from_row(row) for row in rows]

    def load_outcomes(self) -> list[PredictionOutcome]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT record_id, settled_at, group_name, match_id, match_label,
                       predicted_home, predicted_away, actual_home, actual_away, points,
                       exact_ok, winner_ok, home_goals_ok, away_goals_ok, goal_diff_ok
                FROM outcomes
                ORDER BY settled_at ASC, rowid ASC
                """
            ).fetchall()
        return [_outcome_from_row(row) for row in rows]

    def load_research_records(self) -> list[ResearchRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT record_id, created_at, group_name, match_id, match_label, kickoff,
                       home_team, away_team, evidence_json, structured_evidence_json,
                       uncertainty_json, calibration_json, probabilities_json,
                       analysis_dimensions_json, star_player_signals_json
                FROM match_research
                ORDER BY created_at ASC, rowid ASC
                """
            ).fetchall()
        return [_research_record_from_row(row) for row in rows]

    def load_learning_memory(self) -> str:
        return self._load_metadata("learning_memory")

    def write_learning_memory(self, content: str) -> None:
        self._write_metadata("learning_memory", content.strip())

    def load_tournament_state_memory(self) -> str:
        return self._load_metadata("tournament_state")

    def write_tournament_state_memory(self, content: str) -> None:
        self._write_metadata("tournament_state", content.strip())

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            self._create_schema(connection)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS predictions (
                record_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                group_name TEXT NOT NULL,
                match_id TEXT NOT NULL,
                match_label TEXT NOT NULL,
                kickoff TEXT,
                primary_home INTEGER NOT NULL,
                primary_away INTEGER NOT NULL,
                hedge_home INTEGER NOT NULL,
                hedge_away INTEGER NOT NULL,
                submitted_home INTEGER NOT NULL,
                submitted_away INTEGER NOT NULL,
                confidence REAL NOT NULL,
                rationale_json TEXT NOT NULL,
                submitted INTEGER NOT NULL,
                dry_run INTEGER NOT NULL,
                submission_message TEXT NOT NULL,
                probabilities_json TEXT,
                decision_flags_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_predictions_group_match
                ON predictions(group_name, match_id);
            CREATE INDEX IF NOT EXISTS idx_predictions_created_at
                ON predictions(created_at);

            CREATE TABLE IF NOT EXISTS outcomes (
                record_id TEXT PRIMARY KEY,
                settled_at TEXT NOT NULL,
                group_name TEXT NOT NULL,
                match_id TEXT NOT NULL,
                match_label TEXT NOT NULL,
                predicted_home INTEGER NOT NULL,
                predicted_away INTEGER NOT NULL,
                actual_home INTEGER NOT NULL,
                actual_away INTEGER NOT NULL,
                points INTEGER,
                exact_ok INTEGER NOT NULL,
                winner_ok INTEGER NOT NULL,
                home_goals_ok INTEGER NOT NULL,
                away_goals_ok INTEGER NOT NULL,
                goal_diff_ok INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_outcomes_group_match
                ON outcomes(group_name, match_id);
            CREATE INDEX IF NOT EXISTS idx_outcomes_settled_at
                ON outcomes(settled_at);

            CREATE TABLE IF NOT EXISTS match_research (
                record_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                group_name TEXT NOT NULL,
                match_id TEXT NOT NULL,
                match_label TEXT NOT NULL,
                kickoff TEXT,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                structured_evidence_json TEXT NOT NULL,
                uncertainty_json TEXT NOT NULL,
                calibration_json TEXT,
                probabilities_json TEXT,
                analysis_dimensions_json TEXT NOT NULL,
                star_player_signals_json TEXT NOT NULL DEFAULT '[]'
            );

            CREATE INDEX IF NOT EXISTS idx_match_research_group_match
                ON match_research(group_name, match_id);
            CREATE INDEX IF NOT EXISTS idx_match_research_created_at
                ON match_research(created_at);
            """
        )
        _ensure_match_research_star_player_column(connection)
        self._write_metadata("schema_version", str(SCHEMA_VERSION), connection=connection)

    def _insert_prediction(
        self,
        connection: sqlite3.Connection,
        record: PredictionRecord,
    ) -> None:
        connection.execute(
            """
            INSERT OR REPLACE INTO predictions (
                record_id, created_at, group_name, match_id, match_label, kickoff,
                primary_home, primary_away, hedge_home, hedge_away,
                submitted_home, submitted_away, confidence, rationale_json,
                submitted, dry_run, submission_message, probabilities_json,
                decision_flags_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.record_id,
                record.created_at.isoformat(),
                record.group,
                record.match_id,
                record.match_label,
                record.kickoff.isoformat() if record.kickoff else None,
                record.primary.home,
                record.primary.away,
                record.hedge.home,
                record.hedge.away,
                record.submitted_scoreline.home,
                record.submitted_scoreline.away,
                record.confidence,
                json.dumps(record.rationale, ensure_ascii=False),
                _bool_to_int(record.submitted),
                _bool_to_int(record.dry_run),
                record.submission_message,
                _probabilities_to_json(record.probabilities),
                json.dumps(record.decision_flags, ensure_ascii=False),
            ),
        )

    def _insert_outcome(
        self,
        connection: sqlite3.Connection,
        outcome: PredictionOutcome,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO outcomes (
                record_id, settled_at, group_name, match_id, match_label,
                predicted_home, predicted_away, actual_home, actual_away, points,
                exact_ok, winner_ok, home_goals_ok, away_goals_ok, goal_diff_ok
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                outcome.record_id,
                outcome.settled_at.isoformat(),
                outcome.group,
                outcome.match_id,
                outcome.match_label,
                outcome.predicted.home,
                outcome.predicted.away,
                outcome.actual.home,
                outcome.actual.away,
                outcome.points,
                _bool_to_int(outcome.exact_ok),
                _bool_to_int(outcome.winner_ok),
                _bool_to_int(outcome.home_goals_ok),
                _bool_to_int(outcome.away_goals_ok),
                _bool_to_int(outcome.goal_diff_ok),
            ),
        )

    def _insert_research_record(
        self,
        connection: sqlite3.Connection,
        record: ResearchRecord,
    ) -> None:
        connection.execute(
            """
            INSERT INTO match_research (
                record_id, created_at, group_name, match_id, match_label, kickoff,
                home_team, away_team, evidence_json, structured_evidence_json,
                uncertainty_json, calibration_json, probabilities_json,
                analysis_dimensions_json, star_player_signals_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.record_id,
                record.created_at.isoformat(),
                record.group,
                record.match_id,
                record.match_label,
                record.kickoff.isoformat() if record.kickoff else None,
                record.home_team,
                record.away_team,
                json.dumps(record.evidence, ensure_ascii=False),
                _structured_evidence_to_json(record.structured_evidence),
                json.dumps(record.uncertainty, ensure_ascii=False),
                _calibration_to_json(record.calibration),
                _probabilities_to_json(record.probabilities),
                json.dumps(record.analysis_dimensions, ensure_ascii=False, sort_keys=True),
                json.dumps(record.star_player_signals, ensure_ascii=False),
            ),
        )

    def _load_metadata(self, key: str, *, connection: sqlite3.Connection | None = None) -> str:
        own_connection = connection is None
        active_connection = connection or self._connect()
        try:
            row = active_connection.execute(
                "SELECT value FROM metadata WHERE key = ?",
                (key,),
            ).fetchone()
        finally:
            if own_connection:
                active_connection.close()
        return str(row["value"]) if row is not None else ""

    def _write_metadata(
        self,
        key: str,
        value: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        own_connection = connection is None
        active_connection = connection or self._connect()
        try:
            active_connection.execute(
                """
                INSERT INTO metadata(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, datetime.now(self._timezone).isoformat()),
            )
            if own_connection:
                active_connection.commit()
        finally:
            if own_connection:
                active_connection.close()


def _record_from_row(row: sqlite3.Row) -> PredictionRecord:
    return PredictionRecord(
        record_id=str(row["record_id"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        group=str(row["group_name"]),
        match_id=str(row["match_id"]),
        match_label=str(row["match_label"]),
        kickoff=_optional_datetime(row["kickoff"]),
        primary=Scoreline(home=int(row["primary_home"]), away=int(row["primary_away"])),
        hedge=Scoreline(home=int(row["hedge_home"]), away=int(row["hedge_away"])),
        submitted_scoreline=Scoreline(
            home=int(row["submitted_home"]),
            away=int(row["submitted_away"]),
        ),
        confidence=float(row["confidence"]),
        rationale=_json_string_list(row["rationale_json"]),
        submitted=bool(row["submitted"]),
        dry_run=bool(row["dry_run"]),
        submission_message=str(row["submission_message"]),
        probabilities=_probabilities_from_json(row["probabilities_json"]),
        decision_flags=_json_string_list(row["decision_flags_json"]),
    )


def _outcome_from_row(row: sqlite3.Row) -> PredictionOutcome:
    return PredictionOutcome(
        record_id=str(row["record_id"]),
        settled_at=datetime.fromisoformat(str(row["settled_at"])),
        group=str(row["group_name"]),
        match_id=str(row["match_id"]),
        match_label=str(row["match_label"]),
        predicted=Scoreline(home=int(row["predicted_home"]), away=int(row["predicted_away"])),
        actual=Scoreline(home=int(row["actual_home"]), away=int(row["actual_away"])),
        points=_optional_int(row["points"]),
        exact_ok=bool(row["exact_ok"]),
        winner_ok=bool(row["winner_ok"]),
        home_goals_ok=bool(row["home_goals_ok"]),
        away_goals_ok=bool(row["away_goals_ok"]),
        goal_diff_ok=bool(row["goal_diff_ok"]),
    )


def _research_record_from_row(row: sqlite3.Row) -> ResearchRecord:
    return ResearchRecord(
        record_id=str(row["record_id"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        group=str(row["group_name"]),
        match_id=str(row["match_id"]),
        match_label=str(row["match_label"]),
        kickoff=_optional_datetime(row["kickoff"]),
        home_team=str(row["home_team"]),
        away_team=str(row["away_team"]),
        evidence=_json_string_list(row["evidence_json"]),
        structured_evidence=_structured_evidence_from_json(row["structured_evidence_json"]),
        uncertainty=_json_string_list(row["uncertainty_json"]),
        calibration=_calibration_from_json(row["calibration_json"]),
        probabilities=_probabilities_from_json(row["probabilities_json"]),
        analysis_dimensions=_analysis_dimensions_from_json(row["analysis_dimensions_json"]),
        star_player_signals=_json_string_list(row["star_player_signals_json"]),
    )


def _structured_evidence_to_json(items: list[EvidenceItem]) -> str:
    return json.dumps(
        [
            {
                "category": item.category.value,
                "title": item.title,
                "summary": item.summary,
                "url": item.url,
                "source": item.source,
                "tier": item.tier.value,
                "confidence": item.confidence,
            }
            for item in items
        ],
        ensure_ascii=False,
        sort_keys=True,
    )


def _structured_evidence_from_json(value: object) -> list[EvidenceItem]:
    parsed = json.loads(str(value))
    if not isinstance(parsed, list):
        return []
    items: list[EvidenceItem] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        items.append(
            EvidenceItem(
                category=EvidenceCategory(str(item["category"])),
                title=str(item["title"]),
                summary=str(item["summary"]),
                url=str(item["url"]),
                source=str(item["source"]),
                tier=SourceTier(str(item["tier"])),
                confidence=_float(item["confidence"]),
            )
        )
    return items


def _calibration_to_json(value: PredictionCalibration | None) -> str | None:
    if value is None:
        return None
    return json.dumps(
        {
            "evidence_quality": value.evidence_quality,
            "missing_categories": [category.value for category in value.missing_categories],
            "risk_flags": value.risk_flags,
            "draw_risk": value.draw_risk,
            "favorite_bias_risk": value.favorite_bias_risk,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _calibration_from_json(value: object) -> PredictionCalibration | None:
    if value is None:
        return None
    payload = json.loads(str(value)) if isinstance(value, str) else value
    if not isinstance(payload, dict):
        msg = "Invalid calibration JSON"
        raise ValueError(msg)
    missing = []
    for item in _json_list(payload.get("missing_categories", [])):
        try:
            missing.append(EvidenceCategory(str(item)))
        except ValueError:
            continue
    return PredictionCalibration(
        evidence_quality=_float(payload["evidence_quality"]),
        missing_categories=missing,
        risk_flags=[str(item) for item in _json_list(payload.get("risk_flags", []))],
        draw_risk=_float(payload["draw_risk"]),
        favorite_bias_risk=_float(payload["favorite_bias_risk"]),
    )


def _probabilities_to_json(value: ProbabilityProfile | None) -> str | None:
    if value is None:
        return None
    return json.dumps(
        {
            "home_win": value.home_win,
            "draw": value.draw,
            "away_win": value.away_win,
            "over_2_5": value.over_2_5,
            "both_teams_to_score": value.both_teams_to_score,
            "expected_home_goals": value.expected_home_goals,
            "expected_away_goals": value.expected_away_goals,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _probabilities_from_json(value: object) -> ProbabilityProfile | None:
    if value is None:
        return None
    payload = json.loads(str(value)) if isinstance(value, str) else value
    if not isinstance(payload, dict):
        msg = "Invalid probability profile JSON"
        raise ValueError(msg)
    return ProbabilityProfile(
        home_win=_float(payload["home_win"]),
        draw=_float(payload["draw"]),
        away_win=_float(payload["away_win"]),
        over_2_5=_float(payload["over_2_5"]),
        both_teams_to_score=_float(payload["both_teams_to_score"]),
        expected_home_goals=_float(payload["expected_home_goals"]),
        expected_away_goals=_float(payload["expected_away_goals"]),
    )


def _json_string_list(value: object) -> list[str]:
    if value is None:
        return []
    parsed = json.loads(str(value))
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _json_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    return []


def _analysis_dimensions_from_brief(brief: ResearchBrief) -> dict[str, list[str]]:
    corpus_items = [
        *brief.evidence,
        *brief.uncertainty,
        *[
            f"{item.category.value}: {item.title}. {item.summary}"
            for item in brief.structured_evidence
        ],
    ]
    dimensions: dict[str, list[str]] = {key: [] for key in ANALYSIS_DIMENSION_TERMS}
    for key, terms in ANALYSIS_DIMENSION_TERMS.items():
        matches: list[str] = []
        for item in corpus_items:
            normalized = item.casefold()
            if any(term in normalized for term in terms):
                matches.append(item)
            if len(matches) >= 5:
                break
        dimensions[key] = matches
    dimensions["categorias_evidencia"] = sorted(
        {item.category.value for item in brief.structured_evidence}
    )
    missing_categories = brief.calibration.missing_categories if brief.calibration else []
    dimensions["gaps_evidencia"] = [category.value for category in missing_categories]
    return dimensions


def _star_player_signals_from_brief(brief: ResearchBrief) -> list[str]:
    terms = ANALYSIS_DIMENSION_TERMS["jugadores_estrellas_desequilibrantes"]
    player_signal_terms = (
        "alineación",
        "alineacion",
        "asistencias",
        "atacantes",
        "capitán",
        "capitan",
        "convocados",
        "goleador",
        "goleiro",
        "goles",
        "jugadores",
        "mercado",
        "min.",
        "minutos",
        "penaltis",
        "puntos",
        "sustituciones",
        "titular",
        "valores",
    )
    player_signal_categories = {
        EvidenceCategory.PLAYER_CONTEXT,
        EvidenceCategory.AVAILABILITY,
        EvidenceCategory.TACTICS,
        EvidenceCategory.MARKET,
        EvidenceCategory.NEWS,
        EvidenceCategory.RECENT_MATCH_STATS,
    }
    signals: list[str] = []
    seen: set[str] = set()

    def add_signal(value: str) -> None:
        normalized_value = value.strip()
        if not normalized_value or normalized_value in seen or len(signals) >= 8:
            return
        signals.append(normalized_value)
        seen.add(normalized_value)

    for item in brief.structured_evidence:
        text = f"{item.category.value}: {item.title}. {item.summary}"
        normalized = text.casefold()
        if item.category == EvidenceCategory.PLAYER_CONTEXT or (
            item.category in player_signal_categories
            and any(term in normalized for term in player_signal_terms)
        ):
            add_signal(text)

    for raw_signal in brief.evidence:
        normalized = raw_signal.casefold()
        if any(term in normalized for term in terms):
            add_signal(raw_signal)

    return signals
    return signals


def _analysis_dimensions_from_json(value: object) -> dict[str, list[str]]:
    parsed = json.loads(str(value)) if isinstance(value, str) else value
    if not isinstance(parsed, dict):
        return {}
    dimensions: dict[str, list[str]] = {}
    for key, items in parsed.items():
        if isinstance(items, list):
            dimensions[str(key)] = [str(item) for item in items]
        else:
            dimensions[str(key)] = [str(items)]
    return dimensions


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(str(value))


def _float(value: object) -> float:
    if not isinstance(value, int | float | str):
        msg = "Invalid float value"
        raise ValueError(msg)
    return float(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int | float | str):
        msg = "Invalid int value"
        raise ValueError(msg)
    return int(value)


def _bool_to_int(value: bool) -> int:
    return 1 if value else 0


def _ensure_match_research_star_player_column(connection: sqlite3.Connection) -> None:
    columns = {
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(match_research)").fetchall()
    }
    if "star_player_signals_json" not in columns:
        connection.execute(
            "ALTER TABLE match_research "
            "ADD COLUMN star_player_signals_json TEXT NOT NULL DEFAULT '[]'"
        )
