from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from mundialera.domain.models import (
    Prediction,
    PredictionOutcome,
    PredictionRecord,
    ProbabilityProfile,
    Scoreline,
    SubmissionResult,
)
from mundialera.domain.ports import PredictionHistory, PredictionRecorder

SCHEMA_VERSION = 1


class SqlitePredictionStore(PredictionRecorder, PredictionHistory):
    def __init__(self, base_dir: Path, *, timezone_name: str) -> None:
        self._base_dir = base_dir
        self._timezone = ZoneInfo(timezone_name)
        self._database_path = base_dir / "pmundialera.sqlite3"
        self._legacy_predictions_path = base_dir / "predictions.jsonl"
        self._legacy_outcomes_path = base_dir / "outcomes.jsonl"
        self._legacy_learning_path = base_dir / "learning-memory.md"
        self._legacy_tournament_state_path = base_dir / "tournament-state.md"
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @property
    def database_path(self) -> Path:
        return self._database_path

    @property
    def learning_path(self) -> Path:
        return self._database_path

    @property
    def tournament_state_path(self) -> Path:
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
            self._migrate_legacy_files(connection)

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
            """
        )
        self._write_metadata("schema_version", str(SCHEMA_VERSION), connection=connection)

    def _migrate_legacy_files(self, connection: sqlite3.Connection) -> None:
        if self._count_rows(connection, "predictions") == 0:
            for payload in _read_jsonl(self._legacy_predictions_path):
                self._insert_prediction(connection, _record_from_json(payload))
        if self._count_rows(connection, "outcomes") == 0:
            for payload in _read_jsonl(self._legacy_outcomes_path):
                self._insert_outcome(connection, _outcome_from_json(payload))
        if not self._load_metadata("learning_memory", connection=connection):
            self._migrate_markdown_metadata(
                connection,
                key="learning_memory",
                path=self._legacy_learning_path,
            )
        if not self._load_metadata("tournament_state", connection=connection):
            self._migrate_markdown_metadata(
                connection,
                key="tournament_state",
                path=self._legacy_tournament_state_path,
            )

    def _migrate_markdown_metadata(
        self,
        connection: sqlite3.Connection,
        *,
        key: str,
        path: Path,
    ) -> None:
        if path.exists():
            self._write_metadata(
                key,
                path.read_text(encoding="utf-8").strip(),
                connection=connection,
            )

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

    @staticmethod
    def _count_rows(connection: sqlite3.Connection, table_name: str) -> int:
        statements = {
            "predictions": "SELECT COUNT(*) AS count FROM predictions",
            "outcomes": "SELECT COUNT(*) AS count FROM outcomes",
        }
        row = connection.execute(statements[table_name]).fetchone()
        return int(row["count"])


JsonlPredictionStore = SqlitePredictionStore


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


def _record_from_json(payload: dict[str, object]) -> PredictionRecord:
    submitted_scoreline = payload.get("submitted_scoreline", payload["primary"])
    return PredictionRecord(
        record_id=str(payload["record_id"]),
        created_at=datetime.fromisoformat(str(payload["created_at"])),
        group=str(payload["group"]),
        match_id=str(payload["match_id"]),
        match_label=str(payload["match_label"]),
        kickoff=_optional_datetime(payload.get("kickoff")),
        primary=_score_from_json(payload["primary"]),
        hedge=_score_from_json(payload["hedge"]),
        submitted_scoreline=_score_from_json(submitted_scoreline),
        confidence=_float(payload["confidence"]),
        rationale=[str(item) for item in _list(payload.get("rationale", []))],
        submitted=bool(payload["submitted"]),
        dry_run=bool(payload["dry_run"]),
        submission_message=str(payload["submission_message"]),
        probabilities=_probabilities_from_json(payload.get("probabilities")),
        decision_flags=[str(item) for item in _list(payload.get("decision_flags", []))],
    )


def _outcome_from_json(payload: dict[str, object]) -> PredictionOutcome:
    return PredictionOutcome(
        record_id=str(payload["record_id"]),
        settled_at=datetime.fromisoformat(str(payload["settled_at"])),
        group=str(payload["group"]),
        match_id=str(payload["match_id"]),
        match_label=str(payload["match_label"]),
        predicted=_score_from_json(payload["predicted"]),
        actual=_score_from_json(payload["actual"]),
        points=_optional_int(payload.get("points")),
        exact_ok=bool(payload["exact_ok"]),
        winner_ok=bool(payload["winner_ok"]),
        home_goals_ok=bool(payload["home_goals_ok"]),
        away_goals_ok=bool(payload["away_goals_ok"]),
        goal_diff_ok=bool(payload["goal_diff_ok"]),
    )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    items: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                items.append(parsed)
    return items


def _score_from_json(value: object) -> Scoreline:
    if not isinstance(value, dict):
        msg = "Invalid scoreline JSON"
        raise ValueError(msg)
    return Scoreline(home=int(value["home"]), away=int(value["away"]))


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


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return cast(list[object], value)


def _bool_to_int(value: bool) -> int:
    return 1 if value else 0
