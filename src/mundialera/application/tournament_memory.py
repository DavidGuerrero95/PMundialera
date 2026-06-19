from __future__ import annotations

from dataclasses import dataclass

from mundialera.domain.models import (
    EvidenceCategory,
    EvidenceItem,
    Match,
    ResearchBrief,
    SourceTier,
)
from mundialera.domain.ports import ResearchAgent


@dataclass(frozen=True, slots=True)
class TournamentMemoryResearchAgent(ResearchAgent):
    tournament_state_memory: str

    def research(self, match: Match) -> ResearchBrief:
        relevant = _relevant_lines(self.tournament_state_memory, match)
        if not relevant:
            return ResearchBrief(
                match=match,
                uncertainty=["tournament-state: no current tournament state for match teams"],
            )
        summary = " ".join(relevant)
        return ResearchBrief(
            match=match,
            evidence=[f"tournament-state: {summary}"],
            structured_evidence=[
                EvidenceItem(
                    category=EvidenceCategory.RECENT_MATCH_STATS,
                    title="Current tournament team state",
                    summary=summary,
                    url="local://pmundialera/tournament-state",
                    source="pmundialera-local-state",
                    tier=SourceTier.AGGREGATOR,
                    confidence=0.82,
                )
            ],
        )


def _relevant_lines(memory: str, match: Match) -> list[str]:
    home = match.home.name.casefold()
    away = match.away.name.casefold()
    relevant: list[str] = []
    for line in memory.splitlines():
        stripped = line.strip()
        lowered = stripped.casefold()
        if not stripped.startswith("-"):
            continue
        if (
            "average goals" in lowered
            or "draw rate" in lowered
            or "open match rate" in lowered
            or "btts rate" in lowered
            or home in lowered
            or away in lowered
        ):
            relevant.append(stripped)
    return relevant[:12]
