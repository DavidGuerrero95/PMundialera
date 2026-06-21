from __future__ import annotations

from dataclasses import dataclass

from mundialera.application.calibration import calibrate_research_brief
from mundialera.application.pool_strategy import PoolStrategyContext, StrategyMemory
from mundialera.application.probability import (
    build_probability_profile,
    enrich_probability_profile,
    portfolio_hedge_from_profile,
    scoreline_from_profile,
)
from mundialera.application.score_distribution import result_probability
from mundialera.domain.models import EvidenceItem, Match, Prediction, ResearchBrief
from mundialera.domain.ports import PredictionModel, ResearchAgent


class CompositeResearchAgent:
    def __init__(self, agents: list[ResearchAgent]) -> None:
        self._agents = agents

    def research(self, match: Match) -> ResearchBrief:
        evidence: list[str] = []
        structured_evidence: list[EvidenceItem] = []
        uncertainty: list[str] = []
        for agent in self._agents:
            brief = agent.research(match)
            evidence.extend(brief.evidence)
            structured_evidence.extend(brief.structured_evidence)
            uncertainty.extend(brief.uncertainty)
        return enrich_probability_profile(
            calibrate_research_brief(
                ResearchBrief(
                    match=match,
                    evidence=evidence,
                    structured_evidence=structured_evidence,
                    uncertainty=uncertainty,
                )
            )
        )


@dataclass(frozen=True, slots=True)
class PromptBackedResearchAgent:
    name: str
    focus: str

    def research(self, match: Match) -> ResearchBrief:
        return ResearchBrief(
            match=match,
            evidence=[
                f"{self.name}: evaluar {self.focus} para {match.home.name} vs {match.away.name}."
            ],
            uncertainty=[f"{self.name}: requiere investigacion web antes de envio real."],
        )


class HeuristicPredictionModel(PredictionModel):
    """Deterministic baseline until stronger statistical models are added."""

    def __init__(
        self,
        *,
        pool_context: PoolStrategyContext | None = None,
        strategy_memory: StrategyMemory | None = None,
    ) -> None:
        self._pool_context = pool_context
        self._strategy_memory = strategy_memory

    def predict(self, brief: ResearchBrief) -> Prediction:
        match = brief.match
        profile = brief.probability_profile or build_probability_profile(brief)
        primary = scoreline_from_profile(
            profile,
            pool_context=self._pool_context,
            strategy_memory=self._strategy_memory,
        )
        hedge = portfolio_hedge_from_profile(profile, primary)
        confidence = result_probability(profile, primary)
        calibration_penalty = 0.0
        if brief.calibration is not None:
            calibration_penalty = min(
                0.24,
                (1.0 - brief.calibration.evidence_quality) * 0.12
                + brief.calibration.draw_risk * 0.06
                + brief.calibration.favorite_bias_risk * 0.06,
            )
            if (
                brief.calibration.draw_risk >= 0.42
                and primary.home != primary.away
                and abs(primary.home - primary.away) <= 1
            ):
                hedge = portfolio_hedge_from_profile(profile, primary)
        confidence = max(0.20, min(0.85, confidence - calibration_penalty))
        rationale = [
            (
                "Base heuristica deterministica por matriz de marcadores y puntos "
                "esperados GolPredictor."
            ),
            (
                "Perfil probabilistico: "
                f"home={profile.home_win:.2f}, draw={profile.draw:.2f}, "
                f"away={profile.away_win:.2f}, over2.5={profile.over_2_5:.2f}, "
                f"btts={profile.both_teams_to_score:.2f}, "
                f"xG={profile.expected_home_goals:.2f}-{profile.expected_away_goals:.2f}."
            ),
            *brief.evidence[:10],
        ]
        if brief.calibration is not None:
            rationale.append(
                "Calibracion: "
                f"quality={brief.calibration.evidence_quality:.2f}, "
                f"draw_risk={brief.calibration.draw_risk:.2f}, "
                f"favorite_bias={brief.calibration.favorite_bias_risk:.2f}."
            )
            rationale.extend(brief.calibration.risk_flags[:4])
        if brief.uncertainty:
            rationale.append("Incertidumbres activas: " + "; ".join(brief.uncertainty[:6]))
        return Prediction(
            match=match,
            primary=primary,
            hedge=hedge,
            confidence=round(confidence, 2),
            rationale=rationale,
            probabilities=profile,
        )

def default_prompt_research_agents() -> list[ResearchAgent]:
    return [
        PromptBackedResearchAgent(
            "forma-deportiva",
            "racha reciente, xG, resultados y rivales",
        ),
        PromptBackedResearchAgent("plantilla", "lesiones, sanciones, titulares y suplentes"),
        PromptBackedResearchAgent("tactica", "sistema, duelos, presion y balon parado"),
        PromptBackedResearchAgent(
            "contexto",
            "sede, clima, cancha, viaje y factor emocional mundialista",
        ),
        PromptBackedResearchAgent("ranking-elo", "ranking FIFA, ELO y calidad relativa"),
        PromptBackedResearchAgent("mercado-cuotas", "cuotas, consenso publico y valor"),
        PromptBackedResearchAgent("arbitraje-disciplina", "arbitro, tarjetas y penales"),
        PromptBackedResearchAgent("descanso-viaje", "descanso, viaje, huso horario y fatiga"),
        PromptBackedResearchAgent(
            "tabla-incentivos",
            "necesidad de puntos, diferencia de gol y estrategia de grupo",
        ),
        PromptBackedResearchAgent(
            "porteros-defensa",
            "arqueros, centrales, laterales y fragilidad defensiva",
        ),
        PromptBackedResearchAgent("balon-parado", "corners, tiros libres y juego aereo"),
        PromptBackedResearchAgent(
            "mercado-sesgo",
            "evitar sesgo por resultados recientes del torneo",
        ),
    ]


def default_research_agent(
    extra_agents: list[ResearchAgent] | None = None,
) -> CompositeResearchAgent:
    agents = default_prompt_research_agents()
    if extra_agents:
        agents = [*extra_agents, *agents]
    return CompositeResearchAgent(agents=agents)
