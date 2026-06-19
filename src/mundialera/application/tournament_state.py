from __future__ import annotations

from dataclasses import dataclass, field

from mundialera.domain.models import Match, Scoreline


@dataclass(slots=True)
class TeamTournamentState:
    team: str
    played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    open_matches: int = 0
    close_matches: int = 0
    both_teams_scored: int = 0
    form: list[str] = field(default_factory=list)

    def apply(self, goals_for: int, goals_against: int) -> None:
        self.played += 1
        self.goals_for += goals_for
        self.goals_against += goals_against
        if goals_for > goals_against:
            self.wins += 1
            self.form.append("W")
        elif goals_for < goals_against:
            self.losses += 1
            self.form.append("L")
        else:
            self.draws += 1
            self.form.append("D")
        if goals_for + goals_against >= 3:
            self.open_matches += 1
        if abs(goals_for - goals_against) <= 1:
            self.close_matches += 1
        if goals_for > 0 and goals_against > 0:
            self.both_teams_scored += 1

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against

    @property
    def goals_for_avg(self) -> float:
        return self.goals_for / self.played if self.played else 0.0

    @property
    def goals_against_avg(self) -> float:
        return self.goals_against / self.played if self.played else 0.0

    def summary_line(self) -> str:
        return (
            f"- {self.team}: P{self.played} W{self.wins} D{self.draws} L{self.losses}, "
            f"GF {self.goals_for}, GA {self.goals_against}, GD {self.goal_difference:+d}, "
            f"avgGF {self.goals_for_avg:.2f}, avgGA {self.goals_against_avg:.2f}, "
            f"open_profile {_pct(self.open_matches, self.played)}, "
            f"close_profile {_pct(self.close_matches, self.played)}, "
            f"btts_profile {_pct(self.both_teams_scored, self.played)}, "
            f"form {''.join(self.form[-5:]) or '-'}"
        )


def build_tournament_state_memory(matches: list[Match]) -> str:
    settled = _dedupe_settled_matches(matches)
    if not settled:
        return (
            "# PMundialera tournament state\n\n"
            "No settled tournament matches yet. Do not infer team state from future fixtures."
        )

    states: dict[str, TeamTournamentState] = {}
    for match in settled:
        if match.result is None:
            continue
        home = states.setdefault(match.home.name, TeamTournamentState(match.home.name))
        away = states.setdefault(match.away.name, TeamTournamentState(match.away.name))
        home.apply(match.result.home, match.result.away)
        away.apply(match.result.away, match.result.home)

    total_goals = sum(_total_goals(match.result) for match in settled if match.result is not None)
    open_matches = sum(
        1 for match in settled if match.result is not None and _total_goals(match.result) >= 3
    )
    draws = sum(
        1
        for match in settled
        if match.result is not None and match.result.home == match.result.away
    )
    btts = sum(
        1
        for match in settled
        if match.result is not None and match.result.home > 0 and match.result.away > 0
    )

    team_lines = [
        state.summary_line()
        for state in sorted(states.values(), key=lambda item: item.team)
    ]
    hot_attacks = [
        state.team
        for state in states.values()
        if state.played >= 1 and state.goals_for_avg >= 2.5
    ]
    leaky_defenses = [
        state.team
        for state in states.values()
        if state.played >= 1 and state.goals_against_avg >= 2.0
    ]

    lines = [
        "# PMundialera tournament state",
        "",
        "Use this as current in-tournament form, not as permanent team strength.",
        "",
        "## Tournament tempo",
        f"- Settled matches: {len(settled)}",
        f"- Average goals: {total_goals / len(settled):.2f}",
        f"- Draw rate: {_pct(draws, len(settled))}",
        f"- Open match rate (3+ goals): {_pct(open_matches, len(settled))}",
        f"- BTTS rate: {_pct(btts, len(settled))}",
        f"- Hot attacks: {', '.join(sorted(hot_attacks)) if hot_attacks else '-'}",
        f"- Leaky defenses: {', '.join(sorted(leaky_defenses)) if leaky_defenses else '-'}",
        "",
        "## Team state",
        *team_lines,
        "",
        "## Use rules",
        "- Favor current tournament form when both teams already played.",
        "- Treat hot attack versus leaky defense as open-match evidence.",
        "- Treat two close/low-scoring profiles as closed-match evidence.",
        "- Do not erase pre-tournament class; combine it with this state.",
    ]
    return "\n".join(lines)


def _dedupe_settled_matches(matches: list[Match]) -> list[Match]:
    unique: dict[tuple[str, str, str, str], Match] = {}
    for match in matches:
        if match.result is None:
            continue
        key = (match.match_id, match.home.name, match.away.name, match.result.label())
        unique[key] = match
    return sorted(
        unique.values(),
        key=lambda item: item.kickoff.isoformat() if item.kickoff else item.match_id,
    )


def _total_goals(scoreline: Scoreline) -> int:
    return scoreline.home + scoreline.away


def _pct(count: int, total: int) -> str:
    if total == 0:
        return "0.0%"
    return f"{(count / total) * 100:.1f}%"
