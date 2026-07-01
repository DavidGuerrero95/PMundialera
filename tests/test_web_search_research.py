from __future__ import annotations

from mundialera.domain.models import EvidenceCategory, Match, SourceTier, Team
from mundialera.infrastructure.research.web_search import (
    PageSnapshot,
    SearchResult,
    WebSearchResearchAgent,
)


class FakeSearchClient:
    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        _ = query
        return [
            SearchResult(
                title="FIFA match centre lineup update",
                url="https://www.fifa.com/en/matches/example?utm_source=test",
                snippet=(
                    "Official match centre reports likely lineup context and squad availability."
                ),
            ),
            SearchResult(
                title="FIFA match centre lineup update",
                url="https://www.fifa.com/en/matches/example?utm_source=other",
                snippet="Duplicate official item.",
            ),
            SearchResult(
                title="Forum prediction thread",
                url="https://example.test/predictions",
                snippet="Short note.",
            ),
        ][:max_results]

    def fetch_page(self, url: str, *, max_chars: int) -> PageSnapshot | None:
        _ = url
        return PageSnapshot(
            title="Official lineup and player status",
            summary=(
                "Key striker trained normally, the goalkeeper is expected to start, "
                "and the coach addressed recent professional pressure around the squad."
            )[:max_chars],
        )


def test_web_search_research_deduplicates_and_scores_sources() -> None:
    agent = WebSearchResearchAgent(
        FakeSearchClient(),  # type: ignore[arg-type]
        max_queries=1,
        max_results_per_query=3,
    )
    match = Match(match_id="1", kickoff=None, home=Team("A"), away=Team("B"))

    brief = agent.research(match)

    assert len(brief.structured_evidence) == 2
    assert brief.structured_evidence[0].category == EvidenceCategory.AVAILABILITY
    assert brief.structured_evidence[0].tier == SourceTier.OFFICIAL
    assert brief.structured_evidence[0].confidence > brief.structured_evidence[1].confidence
    assert "Key striker trained normally" in brief.structured_evidence[0].summary
    assert "availability|official" in brief.evidence[0]


def test_web_search_research_includes_player_context_queries() -> None:
    queries = WebSearchResearchAgent._queries(
        Match(match_id="1", kickoff=None, home=Team("A"), away=Team("B"))
    )

    assert any(item.category == EvidenceCategory.PLAYER_CONTEXT for item in queries)
    assert any("jugadores estrella desequilibrantes" in item.query for item in queries)
    assert any("mejores jugadores estado forma" in item.query for item in queries)
    assert any("noticias personales profesionales" in item.query for item in queries)
    assert any("jugadores amarillas rojas suspendidos" in item.query for item in queries)
    assert any("titulares suplentes rotacion ritmo" in item.query for item in queries)
    assert any("cambios entrenador esquema" in item.query for item in queries)
    assert any("ultimos 2 anos ultimos 24 meses" in item.query for item in queries)
    assert any("solidez ataque defensa" in item.query for item in queries)
    assert any("ELO FIFA ranking ultimos 2 anos" in item.query for item in queries)
    assert any(item.category == EvidenceCategory.RECENT_MATCH_STATS for item in queries)
    assert any("xG tiros atajadas corners" in item.query for item in queries)
