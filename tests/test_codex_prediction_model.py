from __future__ import annotations

import sys
from pathlib import Path

from mundialera.application.pool_strategy import PoolStrategyContext, StrategyMemory
from mundialera.domain.models import (
    EvidenceCategory,
    EvidenceItem,
    Match,
    PredictionCalibration,
    ProbabilityProfile,
    ResearchBrief,
    SourceTier,
    Team,
)
from mundialera.infrastructure.codex.prediction_model import (
    CodexCliConfig,
    CodexCliPredictionModel,
    _build_prediction_prompt,
)


class FailingFallback:
    def predict(self, brief: ResearchBrief):  # type: ignore[no-untyped-def]
        raise AssertionError("fallback should not be called")


def test_codex_cli_prediction_model_parses_json_response(tmp_path: Path) -> None:
    fake_codex = tmp_path / "fake_codex.py"
    fake_codex.write_text(
        "import json, sys\n"
        "_ = sys.stdin.read()\n"
        "print(json.dumps({"
        "'primary': {'home': 2, 'away': 1}, "
        "'confidence': 0.71, "
        "'rationale': ['better squad availability'], "
        "'risk_flags': ['late lineup change']"
        "}))\n",
        encoding="utf-8",
    )
    model = CodexCliPredictionModel(
        CodexCliConfig(
            executable=sys.executable,
            args=str(fake_codex),
            model=None,
            timeout_seconds=30,
        ),
        fallback=FailingFallback(),
    )
    match = Match(match_id="1", kickoff=None, home=Team("A"), away=Team("B"))

    prediction = model.predict(ResearchBrief(match=match, evidence=["news"], uncertainty=[]))

    assert prediction.primary.label() == "2 - 1"
    assert prediction.hedge == prediction.primary
    assert prediction.confidence == 0.71
    assert prediction.rationale[0] == "Codex CLI prediction engine."


def test_codex_prompt_includes_calibration_payload() -> None:
    match = Match(match_id="1", kickoff=None, home=Team("A"), away=Team("B"))
    brief = ResearchBrief(
        match=match,
        evidence=["market favorite"],
        uncertainty=[],
        calibration=PredictionCalibration(
            evidence_quality=0.42,
            missing_categories=[EvidenceCategory.RECENT_MATCH_STATS],
            risk_flags=["Market signal lacks recent match-stat counterweight."],
            draw_risk=0.58,
            favorite_bias_risk=0.61,
        ),
        probability_profile=ProbabilityProfile(
            home_win=0.28,
            draw=0.34,
            away_win=0.38,
            over_2_5=0.41,
            both_teams_to_score=0.52,
            expected_home_goals=1.05,
            expected_away_goals=1.22,
        ),
        structured_evidence=[
            EvidenceItem(
                category=EvidenceCategory.PLAYER_CONTEXT,
                title="Jugador clave disponible",
                summary="La figura ofensiva llega como estrella desequilibrante y titular.",
                url="https://example.test/player",
                source="example.test",
                tier=SourceTier.GENERIC_WEB,
                confidence=0.61,
            ),
            EvidenceItem(
                category=EvidenceCategory.AVAILABILITY,
                title="Titulares y bajas",
                summary=(
                    "Alineacion probable con suplente revulsivo, lesionado, "
                    "convocado y suspendido."
                ),
                url="https://example.test/availability",
                source="example.test",
                tier=SourceTier.GENERIC_WEB,
                confidence=0.62,
            ),
            EvidenceItem(
                category=EvidenceCategory.REFEREE_DISCIPLINE,
                title="Tarjetas de jugadores",
                summary="Un titular llega con amarillas acumuladas y riesgo de roja.",
                url="https://example.test/cards",
                source="example.test",
                tier=SourceTier.GENERIC_WEB,
                confidence=0.58,
            ),
            EvidenceItem(
                category=EvidenceCategory.FORM,
                title="Ritmo del equipo",
                summary="El equipo llega en buen ritmo, con racha positiva e intensidad alta.",
                url="https://example.test/form",
                source="example.test",
                tier=SourceTier.GENERIC_WEB,
                confidence=0.6,
            ),
        ],
    )

    prompt = _build_prediction_prompt(
        brief,
        learning_memory="# PMundialera tournament state\n- Average goals: 3.25",
        pool_context=PoolStrategyContext(position=40, pool_size=50),
        strategy_memory=StrategyMemory(
            sample_size=24,
            under_total_rate=0.58,
            under_margin_rate=0.54,
            bucket_repetition_rate=0.50,
            repeated_buckets=("2 - 1", "1 - 1"),
        ),
    )

    assert '"calibration"' in prompt
    assert '"probability_profile"' in prompt
    assert '"scoreline_distribution"' in prompt
    assert '"expected_points_candidates"' in prompt
    assert '"optimized_scoreline"' in prompt
    assert "hedge" not in prompt
    assert '"pool_scoring"' in prompt
    assert '"pool_context"' in prompt
    assert '"position": 40' in prompt
    assert '"pool_size": 50' in prompt
    assert '"risk_pressure": 0.7959' in prompt
    assert '"effective_risk_pressure": 0.9359' in prompt
    assert '"strategy": "aggressive_high"' in prompt
    assert '"horizon": "tournament"' in prompt
    assert '"tournament_phase": "final_phase"' in prompt
    assert '"final_phase_aggression": true' in prompt
    assert '"strategy_memory"' in prompt
    assert '"under_total_rate": 0.58' in prompt
    assert '"repeated_buckets": [\n      "2 - 1",' in prompt
    assert '"coverage"' in prompt
    assert '"facts"' in prompt
    assert '"id": "E01"' in prompt
    assert '"draw_risk": 0.58' in prompt
    assert '"expected_home_goals": 1.05' in prompt
    assert prompt.startswith("# Pronostico GolPredictor")
    assert "## Dimensiones obligatorias de analisis" in prompt
    assert "## Jugadores estrella y desequilibrantes" in prompt
    assert "## Reglas de decision" in prompt
    assert "## Formato de salida obligatorio" in prompt
    assert "```json" in prompt
    assert '"star_player_signals"' in prompt
    assert '"team_state_signals"' in prompt
    assert '"lineup_signals"' in prompt
    assert '"bench_rotation_signals"' in prompt
    assert '"availability_signals"' in prompt
    assert '"player_discipline_signals"' in prompt
    assert '"rhythm_signals"' in prompt
    assert '"expected_analysis_dimensions"' in prompt
    assert '"jugadores_diferenciables"' in prompt
    assert '"jugadores_estrellas_desequilibrantes"' in prompt
    assert '"lesionados_sancionados_convocados"' in prompt
    assert '"jugadores_amarillas_rojas_suspendidos"' in prompt
    assert '"faltas_tarjetas"' in prompt
    assert "estrella desequilibrante" in prompt
    assert "amarillas acumuladas" in prompt
    assert "suplente revulsivo" in prompt
    assert "tu respuesta debe ser exclusivamente\n        JSON valido" not in prompt
    assert "tu respuesta debe ser exclusivamente\nJSON valido" in prompt
    assert "marcadores comodos" in prompt
    assert "del favorito" in prompt
    assert "Explica cuando se elige upside sobre EP puro" in prompt
    assert "En `pool_context.tournament_phase = final_phase`" in prompt
    assert "mas varianza controlada" in prompt
    assert "No" in prompt
    assert "No cambies de\nganador sin respaldo probabilistico" in prompt
    assert "Usa `scoreline_distribution` como unica matriz coherente" in prompt
    assert "expected_points_candidates" in prompt
    assert "maximiza los puntos" in prompt
    assert "unico marcador exacto primario" in prompt
    assert "estado de los dos equipos del partido" in prompt
    assert "# PMundialera tournament state" in prompt
    assert "No metas errores tecnicos ni tareas de investigacion como evidencia" in prompt


def test_codex_prompt_uses_match_scoped_star_player_memory() -> None:
    match = Match(
        match_id="32",
        kickoff=None,
        home=Team("Estados Unidos"),
        away=Team("Australia"),
    )
    brief = ResearchBrief(match=match, evidence=[], uncertainty=[])

    prompt = _build_prediction_prompt(
        brief,
        learning_memory=(
            "# PMundialera recent research signals\n"
            "- Estados Unidos - Australia:\n"
            "  - star_player_signal: Pulisic and Balogun are differential attackers.\n"
            "  - lineup_signal: Probable XI includes the same attacking trio.\n"
            "  - availability_signal: One defender is suspended.\n"
            "  - player_discipline_signal: Midfielder has yellow-card accumulation risk.\n"
            "  - rhythm_signal: Team arrives with high rhythm and strong pressure.\n"
            "- Francia - Senegal:\n"
            "  - star_player_signal: unrelated player context.\n"
        ),
    )

    assert "Pulisic and Balogun" in prompt
    assert "unrelated player context" not in prompt
    assert '"star_player_signals": [\n    "Pulisic and Balogun' in prompt
    assert '"lineup_signals": [\n    "Probable XI includes' in prompt
    assert '"availability_signals": [\n    "One defender is suspended' in prompt
    assert '"player_discipline_signals": [\n    "Midfielder has yellow-card' in prompt
    assert '"rhythm_signals": [\n    "Team arrives with high rhythm' in prompt


def test_codex_prompt_filters_generic_metric_pages_from_player_signals() -> None:
    match = Match(match_id="1", kickoff=None, home=Team("A"), away=Team("B"))
    brief = ResearchBrief(
        match=match,
        evidence=["plantilla: evaluar lesiones, sanciones, titulares y suplentes"],
        uncertainty=["plantilla: requiere investigacion web antes de envio real."],
        structured_evidence=[
            EvidenceItem(
                category=EvidenceCategory.RECENT_MATCH_STATS,
                title="Expected Goals (xG) - estadísticas para equipos",
                summary="Página genérica que explica xG y estadísticas de córners.",
                url="https://footystats.org/es/stats/xg",
                source="footystats",
                tier=SourceTier.GENERIC_WEB,
                confidence=0.40,
            )
        ],
    )

    prompt = _build_prediction_prompt(brief, learning_memory="")

    assert '"star_player_signals": []' in prompt
    assert '"lineup_signals": []' in prompt
    assert '"availability_signals": []' in prompt
    assert "plantilla: evaluar" not in prompt
    assert "plantilla: requiere investigacion" not in prompt


def test_codex_prompt_strips_global_team_lists_from_tournament_memory() -> None:
    match = Match(
        match_id="32",
        kickoff=None,
        home=Team("Estados Unidos"),
        away=Team("Australia"),
    )
    brief = ResearchBrief(match=match, evidence=[], uncertainty=[])

    prompt = _build_prediction_prompt(
        brief,
        learning_memory=(
            "# PMundialera tournament state\n"
            "\n"
            "## Tournament tempo\n"
            "- Average goals: 3.18\n"
            "- Draw rate: 35.7%\n"
            "- Hot attacks: Alemania, Estados Unidos, Francia\n"
            "- Leaky defenses: Paraguay, Turquía, Japón\n"
            "\n"
            "## Team state\n"
            "- Estados Unidos: P1 W1 D0 L0, GF 4, GA 1\n"
            "- Australia: P1 W1 D0 L0, GF 2, GA 0\n"
            "- Francia: P1 W1 D0 L0, GF 3, GA 1\n"
        ),
    )

    assert "Average goals: 3.18" in prompt
    assert "Estados Unidos: P1" in prompt
    assert "Australia: P1" in prompt
    assert "Hot attacks" not in prompt
    assert "Leaky defenses" not in prompt
    assert "Francia: P1" not in prompt
