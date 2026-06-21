from __future__ import annotations

import json

from typer.testing import CliRunner

from mundialera.interfaces.cli import app
from mundialera.settings import get_settings


def test_predict_command_returns_auditable_probability_payload(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PMUNDIALERA_ENABLE_WEB_RESEARCH", "false")
    monkeypatch.setenv("PMUNDIALERA_PREDICTION_ENGINE", "heuristic")
    get_settings.cache_clear()
    runner = CliRunner()

    result = runner.invoke(app, ["predict", "--home", "A", "--away", "B"])

    get_settings.cache_clear()
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["match"] == "A - B"
    assert "primary" in payload
    assert "hedge" not in payload
    assert "confidence" in payload
    assert payload["probabilities"]["draw"] >= 0.0
