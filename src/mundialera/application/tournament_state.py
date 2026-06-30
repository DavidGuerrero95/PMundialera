from __future__ import annotations

from dataclasses import dataclass, field

from mundialera.domain.models import Match, Scoreline

KNOCKOUT_HORIZON = "direct_elimination_next_if_qualified"


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
    def points(self) -> int:
        return (self.wins * 3) + self.draws

    @property
    def goals_for_avg(self) -> float:
        return self.goals_for / self.played if self.played else 0.0

    @property
    def goals_against_avg(self) -> float:
        return self.goals_against / self.played if self.played else 0.0

    @property
    def qualification_pressure(self) -> str:
        if self.played == 0:
            return "no_tournament_result"
        if self.played >= 3:
            if self.points >= 6:
                return "likely_direct_qualified"
            if self.points >= 4:
                return "direct_or_best_third_pending"
            if self.points == 3:
                return "best_third_tiebreaker_risk"
            return "eliminated_or_extreme_best_third_risk"
        if self.played >= 2:
            if self.points >= 6:
                return "direct_control"
            if self.points >= 4:
                return "direct_or_best_third_control"
            if self.points == 3:
                return "best_third_possible_win_improves_direct_path"
            return "must_win_best_third_or_elimination_risk"
        if self.points == 3:
            return "early_control"
        if self.points == 1:
            return "early_needs_points"
        return "early_pressure_needs_points"

    @property
    def scoring_posture(self) -> str:
        pressure = self.qualification_pressure
        if "must_win" in pressure or "elimination" in pressure:
            return "needs_result_high_urgency"
        if "best_third_possible" in pressure or "tiebreaker_risk" in pressure:
            return "needs_win_for_direct_path_best_third_floor"
        if "control" in pressure or "qualified" in pressure:
            return "can_manage_result"
        if "needs_points" in pressure:
            return "needs_points"
        return "balanced"

    def summary_line(self) -> str:
        return (
            f"- {self.team}: P{self.played} W{self.wins} D{self.draws} L{self.losses}, "
            f"PTS {self.points}, GF {self.goals_for}, GA {self.goals_against}, "
            f"GD {self.goal_difference:+d}, "
            f"avgGF {self.goals_for_avg:.2f}, avgGA {self.goals_against_avg:.2f}, "
            f"open_profile {_pct(self.open_matches, self.played)}, "
            f"close_profile {_pct(self.close_matches, self.played)}, "
            f"btts_profile {_pct(self.both_teams_scored, self.played)}, "
            f"form {''.join(self.form[-5:]) or '-'}, "
            f"qualification_pressure {self.qualification_pressure}, "
            f"scoring_posture {self.scoring_posture}, "
            f"knockout_horizon {KNOCKOUT_HORIZON}"
        )

    def qualification_line(self) -> str:
        return (
            f"- {self.team}: PTS {self.points}, GD {self.goal_difference:+d}, "
            f"qualification_pressure {self.qualification_pressure}, "
            f"scoring_posture {self.scoring_posture}, "
            "best_third_context possible_if_group_rules_allow, "
            f"knockout_horizon {KNOCKOUT_HORIZON}"
        )


def build_tournament_state_memory(matches: list[Match]) -> str:
    settled = _dedupe_settled_matches(matches)
    if not settled:
        return (
            "# PMundialera tournament state\n\n"
            "No settled tournament matches yet. Do not infer team state from future fixtures."
        )

    states: dict[str, TeamTournamentState] = {}
    group_states: dict[str, dict[str, TeamTournamentState]] = {}
    for match in settled:
        if match.result is None:
            continue
        home = states.setdefault(match.home.name, TeamTournamentState(match.home.name))
        away = states.setdefault(match.away.name, TeamTournamentState(match.away.name))
        home.apply(match.result.home, match.result.away)
        away.apply(match.result.away, match.result.home)
        if match.group:
            group = group_states.setdefault(match.group, {})
            group_home = group.setdefault(match.home.name, TeamTournamentState(match.home.name))
            group_away = group.setdefault(match.away.name, TeamTournamentState(match.away.name))
            group_home.apply(match.result.home, match.result.away)
            group_away.apply(match.result.away, match.result.home)

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
    qualification_lines = [
        state.qualification_line()
        for state in sorted(states.values(), key=lambda item: item.team)
    ]
    group_lines = [
        _group_summary_line(group_name, group)
        for group_name, group in sorted(group_states.items(), key=lambda item: item[0])
        if _is_mapped_tournament_group(group)
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
        "## Group qualification pressure",
        *(group_lines if group_lines else ["- Group state unmapped from current fixtures"]),
        "",
        "## Qualification pressure",
        *qualification_lines,
        "",
        "## Use rules",
        "- Favor current tournament form when both teams already played.",
        "- Treat points, goal difference, best-third risk and must-win context as incentives.",
        "- Treat direct-elimination horizon as a pressure signal, not as proof of open scoring.",
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


def _group_summary_line(group_name: str, group: dict[str, TeamTournamentState]) -> str:
    standings = sorted(
        group.values(),
        key=lambda item: (-item.points, -item.goal_difference, -item.goals_for, item.team),
    )
    parts = [
        (
            f"{state.team} PTS {state.points} GD {state.goal_difference:+d} "
            f"{state.qualification_pressure}"
        )
        for state in standings
    ]
    return f"- Group {group_name}: " + " | ".join(parts)


def _is_mapped_tournament_group(group: dict[str, TeamTournamentState]) -> bool:
    # GolPredictor pool names can arrive as `match.group`; those include the
    # whole tournament and must not be injected as World Cup group context.
    return 2 <= len(group) <= 6


def _pct(count: int, total: int) -> str:
    if total == 0:
        return "0.0%"
    return f"{(count / total) * 100:.1f}%"
