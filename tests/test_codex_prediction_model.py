from __future__ import annotations

import sys
from pathlib import Path

from mundialera.domain.models import (
    EvidenceCategory,
    Match,
    PredictionCalibration,
    ResearchBrief,
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
        "'hedge': {'home': 1, 'away': 1}, "
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
    assert prediction.hedge.label() == "1 - 1"
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
    )

    prompt = _build_prediction_prompt(brief, learning_memory="")

    assert '"calibration"' in prompt
    assert '"draw_risk": 0.58' in prompt
    assert "no uses marcadores comodos del favorito" in prompt
