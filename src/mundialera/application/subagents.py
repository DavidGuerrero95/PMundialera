from __future__ import annotations

import hashlib
from dataclasses import dataclass

from mundialera.domain.models import EvidenceItem, Match, Prediction, ResearchBrief, Scoreline
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
        return ResearchBrief(
            match=match,
            evidence=evidence,
            structured_evidence=structured_evidence,
            uncertainty=uncertainty,
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

    def predict(self, brief: ResearchBrief) -> Prediction:
        match = brief.match
        seed = f"{match.home.name}|{match.away.name}".encode()
        digest = hashlib.sha256(seed).digest()

        home_strength = digest[0] % 4
        away_strength = digest[1] % 4
        home = max(0, min(4, 1 + home_strength - (away_strength // 2)))
        away = max(0, min(4, 1 + away_strength - (home_strength // 2)))

        if match.prediction is not None:
            home = round((home + match.prediction.home) / 2)
            away = round((away + match.prediction.away) / 2)

        primary = Scoreline(home=home, away=away)
        hedge = self._hedge(primary)
        uncertainty_penalty = min(0.25, len(brief.uncertainty) * 0.02)
        evidence_bonus = min(0.12, len(brief.evidence) * 0.005)
        confidence = max(0.35, min(0.82, 0.62 + evidence_bonus - uncertainty_penalty))
        rationale = [
            "Base heuristica deterministica calibrada por equipos y pronostico previo.",
            *brief.evidence[:10],
        ]
        if brief.uncertainty:
            rationale.append("Incertidumbres activas: " + "; ".join(brief.uncertainty[:6]))
        return Prediction(
            match=match,
            primary=primary,
            hedge=hedge,
            confidence=round(confidence, 2),
            rationale=rationale,
        )

    @staticmethod
    def _hedge(primary: Scoreline) -> Scoreline:
        if primary.home == primary.away:
            return Scoreline(home=primary.home + 1, away=primary.away)
        if primary.home > primary.away:
            return Scoreline(home=primary.home, away=max(0, primary.away + 1))
        return Scoreline(home=max(0, primary.home + 1), away=primary.away)


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
