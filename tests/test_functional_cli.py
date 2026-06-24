from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from typer.testing import CliRunner

from mundialera.domain.models import Match, Team
from mundialera.interfaces import cli
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


def test_schedule_command_returns_all_next_matches(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    now = datetime(2026, 6, 24, 15, 50, tzinfo=ZoneInfo("America/Bogota"))
    kickoff = now + timedelta(minutes=70)

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def list_matches(self, group: str) -> list[Match]:
            self.calls.append(group)
            return [
                Match(
                    match_id="49",
                    kickoff=kickoff,
                    home=Team("Escocia"),
                    away=Team("Brasil"),
                    group=group,
                ),
                Match(
                    match_id="50",
                    kickoff=kickoff,
                    home=Team("Marruecos"),
                    away=Team("Haití"),
                    group=group,
                ),
            ]

        def close(self) -> None:
            return None

    class FakeClock:
        def __init__(self, timezone_name: str) -> None:
            self.timezone_name = timezone_name

        def now(self) -> datetime:
            return now

    fake_client = FakeClient()
    monkeypatch.setenv("GOLPREDICTOR_GROUPS", "Mundial CoreX,Mundial FIFA 2026")
    monkeypatch.setattr(cli, "build_golpredictor_client", lambda settings: fake_client)
    monkeypatch.setattr(cli, "SystemClock", FakeClock)
    get_settings.cache_clear()
    runner = CliRunner()

    result = runner.invoke(app, ["run", "schedule"])

    get_settings.cache_clear()
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert fake_client.calls == ["Mundial CoreX"]
    assert payload["configured_groups"] == ["Mundial CoreX", "Mundial FIFA 2026"]
    assert payload["schedule_groups"] == ["Mundial CoreX"]
    assert payload["next_match"]["match_id"] == "49"
    assert [match["match_id"] for match in payload["next_matches"]] == ["49", "50"]
