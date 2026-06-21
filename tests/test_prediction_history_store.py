from __future__ import annotations

from datetime import datetime
from pathlib import Path

from mundialera.domain.models import (
    EvidenceCategory,
    EvidenceItem,
    Match,
    Prediction,
    PredictionCalibration,
    PredictionOutcome,
    ProbabilityProfile,
    ResearchBrief,
    Scoreline,
    SourceTier,
    SubmissionResult,
    Team,
)
from mundialera.infrastructure.local_store.history import SqlitePredictionStore
from mundialera.interfaces.factory import _combined_prediction_memory


def test_prediction_store_persists_probability_profile_and_decision_flags(tmp_path: Path) -> None:
    store = SqlitePredictionStore(tmp_path, timezone_name="America/Bogota")
    match = Match(match_id="1", kickoff=None, home=Team("A"), away=Team("B"), group="G")
    profile = ProbabilityProfile(
        home_win=0.31,
        draw=0.34,
        away_win=0.35,
        over_2_5=0.42,
        both_teams_to_score=0.51,
        expected_home_goals=1.1,
        expected_away_goals=1.2,
    )
    prediction = Prediction(
        match=match,
        primary=Scoreline(1, 1),
        hedge=Scoreline(1, 2),
        confidence=0.52,
        rationale=["audited"],
        probabilities=profile,
        decision_flags=["draw-risk-covered-in-hedge"],
    )

    store.record_prediction(
        prediction,
        SubmissionResult(
            match=match,
            scoreline=prediction.primary,
            submitted=True,
            dry_run=False,
            message="submitted",
        ),
    )

    loaded = store.load_prediction_records()[0]

    assert loaded.probabilities == profile
    assert loaded.decision_flags == ["draw-risk-covered-in-hedge"]
    assert store.database_path.name == "pmundialera.sqlite3"


def test_prediction_store_detects_successful_real_submission(tmp_path: Path) -> None:
    store = SqlitePredictionStore(tmp_path, timezone_name="America/Bogota")
    match = Match(
        match_id="34",
        kickoff=None,
        home=Team("Ecuador"),
        away=Team("Curazao"),
        group="G",
    )
    prediction = Prediction(
        match=match,
        primary=Scoreline(1, 0),
        hedge=Scoreline(1, 0),
        confidence=0.61,
        rationale=["test"],
    )

    store.record_prediction(
        prediction,
        SubmissionResult(
            match=match,
            scoreline=prediction.primary,
            submitted=False,
            dry_run=True,
            message="dry-run",
        ),
    )
    assert not store.has_successful_submission("G", "34")

    store.record_prediction(
        prediction,
        SubmissionResult(
            match=match,
            scoreline=prediction.primary,
            submitted=True,
            dry_run=False,
            message="submitted",
        ),
    )

    assert store.has_successful_submission("G", "34")
    assert not store.has_successful_submission("Other", "34")


def test_prediction_store_persists_tournament_state_memory(tmp_path: Path) -> None:
    store = SqlitePredictionStore(tmp_path, timezone_name="America/Bogota")

    store.write_tournament_state_memory("# state\n- Canada: P1 W1")

    assert store.load_tournament_state_memory() == "# state\n- Canada: P1 W1"


def test_prediction_store_persists_outcomes_idempotently(tmp_path: Path) -> None:
    store = SqlitePredictionStore(tmp_path, timezone_name="America/Bogota")
    outcome = PredictionOutcome(
        record_id="record-1",
        settled_at=datetime.fromisoformat("2026-06-18T12:00:00-05:00"),
        group="Mundial CoreX",
        match_id="1",
        match_label="A - B",
        predicted=Scoreline(2, 1),
        actual=Scoreline(2, 1),
        points=10,
        exact_ok=True,
        winner_ok=True,
        home_goals_ok=True,
        away_goals_ok=True,
        goal_diff_ok=True,
    )

    inserted = store.record_outcomes([outcome, outcome])

    assert inserted == 1
    assert store.load_outcomes() == [outcome]


def test_prediction_store_ignores_legacy_files(tmp_path: Path) -> None:
    (tmp_path / "predictions.jsonl").write_text(
        (
            '{"record_id":"legacy-1","created_at":"2026-06-18T10:00:00-05:00",'
            '"group":"Mundial CoreX","match_id":"1","match_label":"A - B",'
            '"kickoff":null,"primary":{"home":2,"away":1},"hedge":{"home":1,"away":1},'
            '"submitted_scoreline":{"home":2,"away":1},"confidence":0.61,'
            '"rationale":["legacy"],"submitted":true,"dry_run":false,'
            '"submission_message":"legacy","probabilities":{"home_win":0.5,"draw":0.25,'
            '"away_win":0.25,"over_2_5":0.45,"both_teams_to_score":0.5,'
            '"expected_home_goals":1.5,"expected_away_goals":1.0},'
            '"decision_flags":["legacy-flag"]}\n'
        ),
        encoding="utf-8",
    )
    (tmp_path / "outcomes.jsonl").write_text(
        (
            '{"record_id":"legacy-1","settled_at":"2026-06-18T12:00:00-05:00",'
            '"group":"Mundial CoreX","match_id":"1","match_label":"A - B",'
            '"predicted":{"home":2,"away":1},"actual":{"home":2,"away":1},'
            '"points":10,"exact_ok":true,"winner_ok":true,"home_goals_ok":true,'
            '"away_goals_ok":true,"goal_diff_ok":true}\n'
        ),
        encoding="utf-8",
    )
    (tmp_path / "learning-memory.md").write_text("# learning\n- keep calibration", encoding="utf-8")
    (tmp_path / "tournament-state.md").write_text("# state\n- A: P1 W1", encoding="utf-8")
    (tmp_path / "strategy-memory.json").write_text('{"sample_size":99}', encoding="utf-8")

    store = SqlitePredictionStore(tmp_path, timezone_name="America/Bogota")

    assert store.load_prediction_records() == []
    assert store.load_outcomes() == []
    assert store.load_learning_memory() == ""
    assert store.load_tournament_state_memory() == ""
    assert store.load_strategy_memory() == ""


def test_prediction_prompt_memory_uses_sqlite_only(tmp_path: Path) -> None:
    (tmp_path / "learning-memory.md").write_text("# legacy learning", encoding="utf-8")
    (tmp_path / "tournament-state.md").write_text("# legacy state", encoding="utf-8")
    store = SqlitePredictionStore(tmp_path, timezone_name="America/Bogota")
    store.write_learning_memory("# sqlite learning")
    store.write_tournament_state_memory("# sqlite state")
    store.write_strategy_memory('{"sample_size":2}')
    store.record_research_brief(
        ResearchBrief(
            match=Match(match_id="32", kickoff=None, home=Team("USA"), away=Team("Australia")),
            evidence=[],
            structured_evidence=[
                EvidenceItem(
                    category=EvidenceCategory.PLAYER_CONTEXT,
                    title="Star player",
                    summary="Pulisic and Balogun arrive as differential attacking players.",
                    url="https://example.test/star",
                    source="example.test",
                    tier=SourceTier.GENERIC_WEB,
                    confidence=0.66,
                )
            ],
            uncertainty=[],
        )
    )

    memory = _combined_prediction_memory(store)

    assert "# sqlite learning" in memory
    assert "# sqlite state" in memory
    assert "sample_size" not in memory
    assert "# PMundialera recent research signals" in memory
    assert "Pulisic and Balogun" in memory
    assert "legacy" not in memory


def test_prediction_store_persists_match_research_dimensions(tmp_path: Path) -> None:
    store = SqlitePredictionStore(tmp_path, timezone_name="America/Bogota")
    match = Match(
        match_id="32",
        kickoff=datetime.fromisoformat("2026-06-19T14:00:00-05:00"),
        home=Team("Estados Unidos"),
        away=Team("Australia"),
        group="Mundial CoreX",
    )
    profile = ProbabilityProfile(
        home_win=0.44,
        draw=0.28,
        away_win=0.28,
        over_2_5=0.51,
        both_teams_to_score=0.57,
        expected_home_goals=1.45,
        expected_away_goals=1.15,
    )
    brief = ResearchBrief(
        match=match,
        evidence=[
            "grupo abierto con buena forma, racha positiva y necesidad de puntos",
            "hinchada local y estadio con clima pesado",
            "jugador clave llega con buen ritmo y alto xG",
        ],
        structured_evidence=[
            EvidenceItem(
                category=EvidenceCategory.AVAILABILITY,
                title="Titularidad y lesionados",
                summary=(
                    "Alineacion probable, suplente clave, convocado, suspendido "
                    "y lesion defensiva."
                ),
                url="https://example.test/availability",
                source="example.test",
                tier=SourceTier.GENERIC_WEB,
                confidence=0.62,
            ),
            EvidenceItem(
                category=EvidenceCategory.REFEREE_DISCIPLINE,
                title="Arbitro y tarjetas",
                summary=(
                    "Arbitro con promedio alto de tarjetas, faltas y penales; "
                    "titular con amarillas acumuladas y riesgo de roja."
                ),
                url="https://example.test/referee",
                source="example.test",
                tier=SourceTier.GENERIC_WEB,
                confidence=0.58,
            ),
            EvidenceItem(
                category=EvidenceCategory.FORM,
                title="Estado y ritmo",
                summary="Equipo en buen ritmo, racha positiva e intensidad alta.",
                url="https://example.test/form",
                source="example.test",
                tier=SourceTier.GENERIC_WEB,
                confidence=0.6,
            ),
            EvidenceItem(
                category=EvidenceCategory.PLAYER_CONTEXT,
                title="Jugador estrella desequilibrante",
                summary="El jugador clave llega titular, en buen ritmo y con regate diferencial.",
                url="https://example.test/star",
                source="example.test",
                tier=SourceTier.GENERIC_WEB,
                confidence=0.67,
            ),
            EvidenceItem(
                category=EvidenceCategory.GOALKEEPERS_DEFENSE,
                title="Buena defensa y mala defensa",
                summary="Portero local fuerte; visitante concede por laterales.",
                url="https://example.test/defense",
                source="example.test",
                tier=SourceTier.GENERIC_WEB,
                confidence=0.64,
            ),
        ],
        uncertainty=["mercado de empate sin confirmar"],
        calibration=PredictionCalibration(
            evidence_quality=0.55,
            missing_categories=[EvidenceCategory.MARKET],
            risk_flags=["Market signal is missing."],
            draw_risk=0.32,
            favorite_bias_risk=0.28,
        ),
        probability_profile=profile,
    )

    store.record_research_brief(brief)

    loaded = store.load_research_records()[0]
    assert loaded.match_id == "32"
    assert loaded.home_team == "Estados Unidos"
    assert loaded.away_team == "Australia"
    assert loaded.probabilities == profile
    assert loaded.scoreline_distribution
    assert loaded.expected_points_candidates
    assert loaded.expected_points_candidates[0]["expected_pool_points"] > 0
    assert loaded.calibration is not None
    assert loaded.calibration.missing_categories == [EvidenceCategory.MARKET]
    assert loaded.structured_evidence[0].category == EvidenceCategory.AVAILABILITY
    assert loaded.analysis_dimensions["hinchada"]
    assert loaded.analysis_dimensions["titularidad"]
    assert loaded.analysis_dimensions["lesionados_sancionados_convocados"]
    assert loaded.analysis_dimensions["arbitros"]
    assert loaded.analysis_dimensions["faltas_tarjetas"]
    assert loaded.analysis_dimensions["jugadores_amarillas_rojas_suspendidos"]
    assert loaded.analysis_dimensions["buen_ritmo"]
    assert loaded.analysis_dimensions["buen_ataque"]
    assert loaded.analysis_dimensions["buena_defensa"]
    assert loaded.analysis_dimensions["mala_defensa"]
    assert loaded.analysis_dimensions["jugadores_estrellas_desequilibrantes"]
    assert loaded.star_player_signals
    assert loaded.team_state_signals
    assert loaded.lineup_signals
    assert loaded.bench_rotation_signals
    assert loaded.availability_signals
    assert loaded.player_discipline_signals
    assert loaded.rhythm_signals
    assert any("regate diferencial" in item for item in loaded.star_player_signals)
    assert any("Alineacion probable" in item for item in loaded.lineup_signals)
    assert any("suplente clave" in item for item in loaded.bench_rotation_signals)
    assert any("suspendido" in item for item in loaded.availability_signals)
    assert any("amarillas acumuladas" in item for item in loaded.player_discipline_signals)
    assert any("buen ritmo" in item for item in loaded.rhythm_signals)
    assert "market" in loaded.analysis_dimensions["gaps_evidencia"]
