from __future__ import annotations

from mundialera.application.tournament_memory import TournamentMemoryResearchAgent
from mundialera.application.tournament_state import build_tournament_state_memory
from mundialera.domain.models import Match, Scoreline, Team


def test_tournament_state_memory_summarizes_open_and_team_profiles() -> None:
    matches = [
        Match(
            match_id="1",
            kickoff=None,
            home=Team("Canada"),
            away=Team("Qatar"),
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
    assert "Canada: P1 W1 D0 L0, PTS 3, GF 6, GA 0" in memory
    assert "Qatar: P1 W0 D0 L1, PTS 0, GF 0, GA 6" in memory
    assert "Hot attacks: Canada, Suiza" in memory
    assert "Leaky defenses: Bosnia-Herzegovina, Qatar" in memory


def test_tournament_state_memory_adds_group_and_best_third_pressure() -> None:
    matches = [
        Match(
            match_id="1",
            kickoff=None,
            group="Grupo E",
            home=Team("Ecuador"),
            away=Team("Curazao"),
            result=Scoreline(2, 0),
        ),
        Match(
            match_id="2",
            kickoff=None,
            group="Grupo E",
            home=Team("Alemania"),
            away=Team("Ecuador"),
            result=Scoreline(2, 1),
        ),
        Match(
            match_id="3",
            kickoff=None,
            group="Grupo E",
            home=Team("Alemania"),
            away=Team("Costa de Marfil"),
            result=Scoreline(2, 0),
        ),
    ]

    memory = build_tournament_state_memory(matches)

    assert "## Group qualification pressure" in memory
    assert "- Group Grupo E:" in memory
    assert "Ecuador PTS 3 GD +1 best_third_possible_win_improves_direct_path" in memory
    assert "qualification_pressure best_third_possible_win_improves_direct_path" in memory
    assert "scoring_posture needs_win_for_direct_path_best_third_floor" in memory
    assert "best_third_context possible_if_group_rules_allow" in memory
    assert "knockout_horizon direct_elimination_next_if_qualified" in memory


def test_tournament_memory_agent_filters_match_relevant_state() -> None:
    memory = "\n".join(
        [
            "# PMundialera tournament state",
            "- Average goals: 3.25",
            "- Draw rate: 22.0%",
            "- Open match rate (3+ goals): 68.0%",
            "- Hot attacks: Canada, Francia",
            "- Leaky defenses: Qatar, Francia",
            (
                "- Group Grupo A: Canada PTS 3 GD +6 early_control | "
                "Qatar PTS 0 GD -6 early_pressure_needs_points"
            ),
            "- Group Grupo B: Francia PTS 3 GD +2 early_control",
            "- Canada: P1 W1 D0 L0, PTS 3, GF 6, GA 0, open_profile 100.0%",
            "- Qatar: P1 W0 D0 L1, PTS 0, GF 0, GA 6, open_profile 100.0%",
            "- Francia: P1 W1 D0 L0, PTS 3, GF 3, GA 1, open_profile 100.0%",
        ]
    )
    match = Match(
        match_id="3",
        kickoff=None,
        group="Grupo A",
        home=Team("Canada"),
        away=Team("Qatar"),
    )

    brief = TournamentMemoryResearchAgent(memory).research(match)

    assert brief.structured_evidence
    assert len(brief.structured_evidence) == 2
    assert "Canada" in brief.evidence[0]
    assert "Qatar" in brief.evidence[0]
    assert "Francia" not in brief.evidence[0]
    assert "Grupo A" in brief.evidence[0]
    assert "Grupo B" not in brief.evidence[0]
    assert "Hot attacks" not in brief.evidence[0]
    assert "Leaky defenses" not in brief.evidence[0]
