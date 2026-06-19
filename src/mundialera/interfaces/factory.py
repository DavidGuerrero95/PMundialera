from __future__ import annotations

from pathlib import Path

from mundialera.application.clock import SystemClock
from mundialera.application.feedback import FeedbackService
from mundialera.application.orchestrator import PredictionOrchestrator
from mundialera.application.subagents import HeuristicPredictionModel, default_research_agent
from mundialera.application.tournament_memory import TournamentMemoryResearchAgent
from mundialera.domain.ports import PredictionModel, ResearchAgent
from mundialera.infrastructure.codex.prediction_model import CodexCliConfig, CodexCliPredictionModel
from mundialera.infrastructure.golpredictor.client import (
    GolPredictorClient,
    GolPredictorCredentials,
)
from mundialera.infrastructure.local_store.history import JsonlPredictionStore
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


def build_prediction_store(settings: Settings | None = None) -> JsonlPredictionStore:
    resolved = settings or get_settings()
    return JsonlPredictionStore(
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


def _combined_prediction_memory(store: JsonlPredictionStore) -> str:
    sections = [
        item
        for item in (store.load_learning_memory(), store.load_tournament_state_memory())
        if item
    ]
    return "\n\n".join(sections)


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
        hedge_group_names=resolved.hedge_groups(),
        recorder=store,
    )


def build_feedback_service(settings: Settings | None = None) -> FeedbackService:
    resolved = settings or get_settings()
    return FeedbackService(
        fixtures=build_golpredictor_client(resolved),
        store=build_prediction_store(resolved),
        now=SystemClock(resolved.pmundialera_timezone).now(),
    )
