from __future__ import annotations

from pathlib import Path

from mundialera.infrastructure.golpredictor.client import parse_matches


def test_parse_golpredictor_group_table() -> None:
    html = Path("tests/fixtures/golpredictor_group.html").read_text(encoding="utf-8")

    matches = parse_matches(html, group_name="Mundial CoreX", timezone_name="America/Bogota")

    assert len(matches) == 2
    assert matches[0].match_id == "14"
    assert matches[0].label == "España - Cabo Verde"
    assert matches[0].prediction is not None
    assert matches[0].prediction.label() == "4 - 0"
    assert matches[0].result is not None
    assert matches[0].result.label() == "0 - 0"
    assert matches[0].points == 2
    assert matches[1].prediction is None
    assert matches[1].kickoff is not None
    assert matches[1].kickoff.year == 2026
