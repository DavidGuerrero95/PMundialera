from __future__ import annotations

from mundialera.application.tournament_memory import TournamentMemoryResearchAgent
from mundialera.application.tournament_state import build_tournament_state_memory
from mundialera.domain.models import Match, Scoreline, Team


def test_tournament_state_memory_summarizes_open_and_team_profiles() -> None:
    matches = [
        Match(
            match_id="1",
            kickoff=None,
            home=Team("Canadá"),
            away=Team("Catar"),
            result=Scoreline(6, 0),
        ),
        Match(
            match_id="2",
            kickoff=None,
            home=Team("Suiza"),
            away=Team("Bosnia-Herzegovina"),
            result=Scoreline(4, 1),
        ),
        Match(
            match_id="2",
            kickoff=None,
            home=Team("Suiza"),
            away=Team("Bosnia-Herzegovina"),
            result=Scoreline(4, 1),
        ),
    ]

    memory = build_tournament_state_memory(matches)

    assert "- Settled matches: 2" in memory
    assert "- Open match rate (3+ goals): 100.0%" in memory
    assert "Canadá: P1 W1 D0 L0, GF 6, GA 0" in memory
    assert "Catar: P1 W0 D0 L1, GF 0, GA 6" in memory
    assert "Hot attacks: Canadá, Suiza" in memory
    assert "Leaky defenses: Bosnia-Herzegovina, Catar" in memory


def test_tournament_memory_agent_filters_match_relevant_state() -> None:
    memory = "\n".join(
        [
            "# PMundialera tournament state",
            "- Average goals: 3.25",
            "- Draw rate: 22.0%",
            "- Open match rate (3+ goals): 68.0%",
            "- Canadá: P1 W1 D0 L0, GF 6, GA 0, open_profile 100.0%",
            "- Catar: P1 W0 D0 L1, GF 0, GA 6, open_profile 100.0%",
            "- Francia: P1 W1 D0 L0, GF 3, GA 1, open_profile 100.0%",
        ]
    )
    match = Match(match_id="3", kickoff=None, home=Team("Canadá"), away=Team("Catar"))

    brief = TournamentMemoryResearchAgent(memory).research(match)

    assert brief.structured_evidence
    assert "Canadá" in brief.evidence[0]
    assert "Catar" in brief.evidence[0]
    assert "Francia" not in brief.evidence[0]
