from __future__ import annotations

import re
from pathlib import Path

from mundialera.application.clock import SystemClock
from mundialera.application.feedback import FeedbackService
from mundialera.application.orchestrator import PredictionOrchestrator
from mundialera.application.subagents import HeuristicPredictionModel, default_research_agent
from mundialera.application.tournament_memory import TournamentMemoryResearchAgent
from mundialera.domain.models import ResearchRecord
from mundialera.domain.ports import PredictionModel, ResearchAgent
from mundialera.infrastructure.codex.prediction_model import CodexCliConfig, CodexCliPredictionModel
from mundialera.infrastructure.golpredictor.client import (
    GolPredictorClient,
    GolPredictorCredentials,
)
from mundialera.infrastructure.local_store.history import SqlitePredictionStore
from mundialera.infrastructure.research.web_search import (
    DuckDuckGoSearchClient,
    WebSearchResearchAgent,
)
from mundialera.settings import Settings, get_settings


def build_golpredictor_client(settings: Settings | None = None) -> GolPredictorClient:
    resolved = settings or get_settings()
    username, password = resolved.require_golpredictor_credentials()
    return GolPredictorClient(
        base_url=resolved.golpredictor_base_url,
        credentials=GolPredictorCredentials(username=username, password=password),
        timezone_name=resolved.pmundialera_timezone,
    )


def build_prediction_store(settings: Settings | None = None) -> SqlitePredictionStore:
    resolved = settings or get_settings()
    return SqlitePredictionStore(
        Path(resolved.pmundialera_data_dir),
        timezone_name=resolved.pmundialera_timezone,
    )


def build_prediction_model(settings: Settings | None = None) -> PredictionModel:
    resolved = settings or get_settings()
    store = build_prediction_store(resolved)
    heuristic_model = HeuristicPredictionModel()
    if resolved.pmundialera_prediction_engine.casefold() != "codex":
        return heuristic_model
    context_memory = _combined_prediction_memory(store)
    return CodexCliPredictionModel(
        CodexCliConfig(
            executable=resolved.pmundialera_codex_executable,
            args=resolved.pmundialera_codex_args,
            model=resolved.pmundialera_codex_model,
            timeout_seconds=resolved.pmundialera_codex_timeout_seconds,
        ),
        fallback=heuristic_model,
        learning_memory=context_memory,
    )


def build_research_agent(settings: Settings | None = None) -> ResearchAgent:
    resolved = settings or get_settings()
    extra_research_agents: list[ResearchAgent] = []
    tournament_state = build_prediction_store(resolved).load_tournament_state_memory()
    if tournament_state:
        extra_research_agents.append(TournamentMemoryResearchAgent(tournament_state))
    if resolved.pmundialera_enable_web_research:
        extra_research_agents.append(
            WebSearchResearchAgent(
                DuckDuckGoSearchClient(),
                max_queries=resolved.pmundialera_max_research_queries,
                max_results_per_query=resolved.pmundialera_max_results_per_query,
                enable_page_scrape=resolved.pmundialera_enable_page_scrape,
                max_pages_per_query=resolved.pmundialera_max_pages_per_query,
                max_scraped_chars=resolved.pmundialera_max_scraped_chars,
            )
        )
    return default_research_agent(extra_research_agents)


def _combined_prediction_memory(store: SqlitePredictionStore) -> str:
    sections = [
        item
        for item in (
            store.load_learning_memory(),
            store.load_tournament_state_memory(),
            _recent_research_memory(store),
        )
        if item
    ]
    return "\n\n".join(sections)


def _recent_research_memory(store: SqlitePredictionStore) -> str:
    lines = ["# PMundialera recent research signals"]
    for record in store.load_research_records()[-8:]:
        signals = _record_research_signals(record)
        if not signals:
            continue
        lines.append(f"- {record.match_label}:")
        for label, signal in signals[:8]:
            lines.append(f"  - {label}: {_compact_memory_line(signal)}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _record_research_signals(record: ResearchRecord) -> list[tuple[str, str]]:
    labeled_groups = (
        ("star_player_signal", record.star_player_signals),
        ("team_state_signal", record.team_state_signals),
        ("lineup_signal", record.lineup_signals),
        ("bench_rotation_signal", record.bench_rotation_signals),
        ("availability_signal", record.availability_signals),
        ("player_discipline_signal", record.player_discipline_signals),
        ("rhythm_signal", record.rhythm_signals),
    )
    signals: list[tuple[str, str]] = []
    for label, values in labeled_groups:
        for value in values[:2]:
            if _usable_research_signal(value):
                signals.append((label, value))
    return signals


def _usable_star_player_signal(value: str) -> bool:
    return _usable_research_signal(value)


def _usable_research_signal(value: str) -> bool:
    normalized = value.casefold()
    negative_markers = (
        "sin resultados",
        "fallo consulta",
        "page-scrape: fallo",
        "connecterror",
        "httpstatuserror",
        ": evaluar ",
        "requiere investigacion",
        "requiere investigación",
        "antes de envio real",
        "antes de envío real",
        "que es xg",
        "qué es xg",
        "expected goals (xg)",
        "estadisticas xg para equipos",
        "estadísticas xg para equipos",
        "estadisticas de corners",
        "estadísticas de córners",
        "corner-stats",
        "/stats/xg",
        "footystats",
    )
    return not any(marker in normalized for marker in negative_markers)


def _compact_memory_line(value: str, *, limit: int = 1000) -> str:
    line = _sanitize_context_text(" ".join(value.split()))
    if len(line) <= limit:
        return line
    return f"{line[: limit - 3]}..."


def _sanitize_context_text(value: str) -> str:
    without_hot = re.sub(
        r"\s*-\s*Hot attacks:.*?(?=\s*-\s*(?:Leaky defenses:|[A-ZÁÉÍÓÚÑ][^:]{1,80}:)|$)",
        "",
        value,
    )
    return re.sub(
        r"\s*-\s*Leaky defenses:.*?(?=\s*-\s*[A-ZÁÉÍÓÚÑ][^:]{1,80}:|$)",
        "",
        without_hot,
    ).strip()


def build_orchestrator(settings: Settings | None = None) -> PredictionOrchestrator:
    resolved = settings or get_settings()
    client = build_golpredictor_client(resolved)
    store = build_prediction_store(resolved)
    return PredictionOrchestrator(
        fixtures=client,
        research_agent=build_research_agent(resolved),
        prediction_model=build_prediction_model(resolved),
        sink=client,
        clock=SystemClock(resolved.pmundialera_timezone),
        submission_window_minutes=resolved.pmundialera_submission_window_minutes,
        recorder=store,
        research_recorder=store,
    )


def build_feedback_service(settings: Settings | None = None) -> FeedbackService:
    resolved = settings or get_settings()
    return FeedbackService(
        fixtures=build_golpredictor_client(resolved),
        store=build_prediction_store(resolved),
        now=SystemClock(resolved.pmundialera_timezone).now(),
    )
