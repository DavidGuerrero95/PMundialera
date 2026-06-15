from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from mundialera.domain.models import (
    EvidenceCategory,
    EvidenceItem,
    Match,
    ResearchBrief,
    SourceTier,
)
from mundialera.domain.ports import ResearchAgent


@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str


@dataclass(frozen=True, slots=True)
class QuerySpec:
    category: EvidenceCategory
    query: str


@dataclass(frozen=True, slots=True)
class PageSnapshot:
    title: str
    summary: str


class SearchClient(Protocol):
    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        """Return web search results for a query."""

    def fetch_page(self, url: str, *, max_chars: int) -> PageSnapshot | None:
        """Return extracted page text when the page is safely reachable."""


class DuckDuckGoSearchClient:
    def __init__(self, *, timeout_seconds: float = 15.0) -> None:
        self._client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "PMundialera/0.1 research"},
        )

    def close(self) -> None:
        self._client.close()

    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        response = self._client.get("https://duckduckgo.com/html/", params={"q": query})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        results: list[SearchResult] = []
        for result in soup.select(".result"):
            title_node = result.select_one(".result__a")
            snippet_node = result.select_one(".result__snippet")
            if not isinstance(title_node, Tag):
                continue
            title = title_node.get_text(" ", strip=True)
            href = _clean_duckduckgo_url(str(title_node.get("href", "")))
            snippet = (
                snippet_node.get_text(" ", strip=True) if isinstance(snippet_node, Tag) else ""
            )
            if title and href:
                results.append(SearchResult(title=title, url=href, snippet=snippet))
            if len(results) >= max_results:
                break
        return results

    def fetch_page(self, url: str, *, max_chars: int) -> PageSnapshot | None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return None
        if parsed.path.casefold().endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx")):
            return None
        response = self._client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type:
            return None
        soup = BeautifulSoup(response.text, "html.parser")
        for node in soup(["script", "style", "noscript", "svg"]):
            node.decompose()
        title_node = soup.find("title")
        title = title_node.get_text(" ", strip=True) if isinstance(title_node, Tag) else ""
        summary = _extract_page_summary(soup, max_chars=max_chars)
        if not summary:
            return None
        return PageSnapshot(title=title, summary=summary)


class WebSearchResearchAgent(ResearchAgent):
    def __init__(
        self,
        search_client: SearchClient,
        *,
        max_queries: int,
        max_results_per_query: int,
        enable_page_scrape: bool = True,
        max_pages_per_query: int = 2,
        max_scraped_chars: int = 1800,
    ) -> None:
        self._search_client = search_client
        self._max_queries = max_queries
        self._max_results_per_query = max_results_per_query
        self._enable_page_scrape = enable_page_scrape
        self._max_pages_per_query = max_pages_per_query
        self._max_scraped_chars = max_scraped_chars

    def research(self, match: Match) -> ResearchBrief:
        evidence: list[str] = []
        structured_evidence: list[EvidenceItem] = []
        uncertainty: list[str] = []
        seen: set[str] = set()
        for query in self._queries(match)[: self._max_queries]:
            try:
                results = self._search_client.search(
                    query.query,
                    max_results=self._max_results_per_query,
                )
            except httpx.HTTPError as exc:
                uncertainty.append(
                    f"web-search: fallo consulta '{query.query}': {exc.__class__.__name__}"
                )
                continue
            if not results:
                uncertainty.append(f"web-search: sin resultados para '{query.query}'")
                continue
            scraped_for_query = 0
            for item in results:
                dedupe_key = _dedupe_key(item)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                source = _source_from_url(item.url)
                tier = _source_tier(source)
                page = None
                if self._enable_page_scrape and scraped_for_query < self._max_pages_per_query:
                    try:
                        page = self._search_client.fetch_page(
                            item.url,
                            max_chars=self._max_scraped_chars,
                        )
                        scraped_for_query += 1
                    except httpx.HTTPError as exc:
                        uncertainty.append(
                            f"page-scrape: fallo '{item.url}': {exc.__class__.__name__}"
                        )
                summary = _merge_summary(item.snippet, page.summary if page else "")
                confidence = _source_confidence(tier, summary, scraped=page is not None)
                structured_item = EvidenceItem(
                    category=query.category,
                    title=page.title or item.title if page else item.title,
                    summary=summary,
                    url=item.url,
                    source=source,
                    tier=tier,
                    confidence=confidence,
                )
                structured_evidence.append(structured_item)
                evidence.append(
                    "web-search: "
                    f"[{query.category.value}|{tier.value}|{confidence:.2f}] "
                    f"{structured_item.title} | {summary} | {item.url}"
                )
        if not structured_evidence:
            uncertainty.append("web-search: no se obtuvo evidencia web deduplicada")
        return ResearchBrief(
            match=match,
            evidence=evidence,
            structured_evidence=structured_evidence,
            uncertainty=uncertainty,
        )

    @staticmethod
    def _queries(match: Match) -> list[QuerySpec]:
        label = f"{match.home.name} {match.away.name}"
        return [
            QuerySpec(
                EvidenceCategory.AVAILABILITY,
                f"{label} alineaciones oficiales probables lesiones sancionados mundial 2026",
            ),
            QuerySpec(
                EvidenceCategory.AVAILABILITY,
                f"{label} bajas ultima hora convocatoria molestias entrenamiento mundial 2026",
            ),
            QuerySpec(
                EvidenceCategory.PLAYER_CONTEXT,
                f"{label} jugadores clave rendimiento individual minutos recientes mundial 2026",
            ),
            QuerySpec(
                EvidenceCategory.PLAYER_CONTEXT,
                f"{label} noticias personales profesionales jugadores entrenador "
                "capitan mundial 2026",
            ),
            QuerySpec(
                EvidenceCategory.TACTICS,
                f"{label} previa tactica titulares suplentes entrenadores mundial 2026",
            ),
            QuerySpec(
                EvidenceCategory.VENUE_WEATHER,
                f"{label} estadio sede clima cancha hora partido mundial 2026",
            ),
            QuerySpec(
                EvidenceCategory.FORM,
                f"{match.home.name} forma reciente {match.away.name} "
                "forma reciente ultimos partidos",
            ),
            QuerySpec(
                EvidenceCategory.NEWS,
                f"{label} noticias recientes hoy previa pronostico marcador mundial 2026",
            ),
            QuerySpec(
                EvidenceCategory.MARKET,
                f"{label} cuotas apuestas probabilidades mercado mundial 2026",
            ),
            QuerySpec(
                EvidenceCategory.RANKING,
                f"{label} ranking FIFA ELO calidad plantel previo mundial 2026",
            ),
            QuerySpec(
                EvidenceCategory.REFEREE_DISCIPLINE,
                f"{label} arbitro tarjetas penales disciplina mundial 2026",
            ),
            QuerySpec(
                EvidenceCategory.TABLE_INCENTIVES,
                f"{label} grupo tabla puntos diferencia gol incentivos mundial 2026",
            ),
            QuerySpec(
                EvidenceCategory.REST_TRAVEL,
                f"{label} descanso viaje fatiga rotacion calendario mundial 2026",
            ),
            QuerySpec(
                EvidenceCategory.GOALKEEPERS_DEFENSE,
                f"{label} porteros defensa centrales bajas defensivas mundial 2026",
            ),
            QuerySpec(
                EvidenceCategory.SET_PIECES,
                f"{label} balon parado corners tiros libres juego aereo mundial 2026",
            ),
        ]


def _clean_duckduckgo_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.path == "/l/":
        uddg = parse_qs(parsed.query).get("uddg")
        if uddg:
            return unquote(uddg[0])
    return value


def _dedupe_key(result: SearchResult) -> str:
    canonical_url = _canonical_url(result.url)
    if canonical_url:
        return canonical_url
    return _normalize_text(result.title)


def _canonical_url(value: str) -> str:
    parsed = urlparse(value)
    if not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/")
    return f"{parsed.netloc.casefold()}{path.casefold()}"


def _normalize_text(value: str) -> str:
    lowered = value.casefold()
    return re.sub(r"[^a-z0-9]+", " ", lowered).strip()


def _merge_summary(snippet: str, page_summary: str) -> str:
    parts = [part.strip() for part in (snippet, page_summary) if part.strip()]
    if not parts:
        return ""
    return " ".join(dict.fromkeys(parts))


def _extract_page_summary(soup: BeautifulSoup, *, max_chars: int) -> str:
    meta = soup.find("meta", attrs={"name": "description"})
    candidates: list[str] = []
    if isinstance(meta, Tag):
        content = meta.get("content")
        if isinstance(content, str):
            candidates.append(content)
    for selector in ("article", "main", "p"):
        for node in soup.select(selector):
            text = node.get_text(" ", strip=True)
            if len(text) >= 80:
                candidates.append(text)
            if sum(len(item) for item in candidates) >= max_chars:
                break
        if sum(len(item) for item in candidates) >= max_chars:
            break
    summary = _clean_text(" ".join(candidates))
    return summary[:max_chars].strip()


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _source_from_url(value: str) -> str:
    parsed = urlparse(value)
    host = parsed.netloc.casefold()
    if host.startswith("www."):
        return host[4:]
    return host


def _source_tier(source: str) -> SourceTier:
    official_domains = (
        "fifa.com",
        "concacaf.com",
        "conmebol.com",
        "uefa.com",
    )
    recognized_media_domains = (
        "apnews.com",
        "bbc.com",
        "bbc.co.uk",
        "espn.com",
        "reuters.com",
        "skysports.com",
        "theathletic.com",
    )
    aggregator_domains = (
        "11v11.com",
        "flashscore.com",
        "oddsportal.com",
        "soccerway.com",
        "sofascore.com",
        "transfermarkt.com",
        "worldfootball.net",
    )
    if source.endswith(official_domains):
        return SourceTier.OFFICIAL
    if source.endswith(recognized_media_domains):
        return SourceTier.RECOGNIZED_MEDIA
    if source.endswith(aggregator_domains):
        return SourceTier.AGGREGATOR
    return SourceTier.GENERIC_WEB


def _source_confidence(tier: SourceTier, summary: str, *, scraped: bool) -> float:
    base = {
        SourceTier.OFFICIAL: 0.92,
        SourceTier.RECOGNIZED_MEDIA: 0.82,
        SourceTier.AGGREGATOR: 0.72,
        SourceTier.GENERIC_WEB: 0.55,
    }[tier]
    summary_bonus = 0.04 if len(summary.strip()) >= 80 else 0.0
    scrape_bonus = 0.03 if scraped else 0.0
    return min(0.98, base + summary_bonus + scrape_bonus)
