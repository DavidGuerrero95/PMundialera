from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass

from mundialera.domain.models import Prediction, ResearchBrief, Scoreline
from mundialera.domain.ports import PredictionModel


class CodexPredictionError(RuntimeError):
    """Raised when Codex CLI cannot produce a valid prediction."""


@dataclass(frozen=True, slots=True)
class CodexCliConfig:
    executable: str
    args: str
    model: str | None
    timeout_seconds: int


class CodexCliPredictionModel(PredictionModel):
    def __init__(
        self,
        config: CodexCliConfig,
        *,
        fallback: PredictionModel,
        learning_memory: str = "",
    ) -> None:
        self._config = config
        self._fallback = fallback
        self._learning_memory = learning_memory

    def predict(self, brief: ResearchBrief) -> Prediction:
        prompt = _build_prediction_prompt(brief, learning_memory=self._learning_memory)
        try:
            payload = self._run_codex(prompt)
            return _prediction_from_payload(brief, payload)
        except (CodexPredictionError, OSError, subprocess.SubprocessError) as exc:
            fallback = self._fallback.predict(brief)
            return Prediction(
                match=fallback.match,
                primary=fallback.primary,
                hedge=fallback.hedge,
                confidence=min(fallback.confidence, 0.45),
                rationale=[
                    f"Codex CLI unavailable or invalid response: {exc.__class__.__name__}: {exc}",
                    *fallback.rationale,
                ],
            )

    def _run_codex(self, prompt: str) -> dict[str, object]:
        args = _split_args(self._config.args)
        if self._config.model:
            args = _inject_model_arg(args, self._config.model)
        command = _build_command(self._config.executable, args)
        completed = subprocess.run(  # noqa: S603
            command,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self._config.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip()[-500:]
            raise CodexPredictionError(f"codex exit={completed.returncode}: {stderr}")
        return _extract_json_object(completed.stdout)


def _split_args(value: str) -> list[str]:
    if not value.strip():
        return []
    return shlex.split(value, posix=os.name != "nt")


def _build_command(executable: str, args: list[str]) -> list[str]:
    resolved = shutil.which(executable) or executable
    if os.name == "nt" and resolved.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", resolved, *args]
    return [resolved, *args]


def _inject_model_arg(args: list[str], model: str) -> list[str]:
    if not args:
        return ["--model", model]
    try:
        prompt_index = args.index("-")
    except ValueError:
        return [*args, "--model", model]
    return [*args[:prompt_index], "--model", model, *args[prompt_index:]]


def _build_prediction_prompt(brief: ResearchBrief, *, learning_memory: str) -> str:
    match = brief.match
    context = {
        "match": {
            "id": match.match_id,
            "group": match.group,
            "kickoff": match.kickoff.isoformat() if match.kickoff else None,
            "home": match.home.name,
            "away": match.away.name,
            "current_prediction": match.prediction.label() if match.prediction else None,
            "result": match.result.label() if match.result else None,
            "points": match.points,
        },
        "evidence": brief.evidence,
        "structured_evidence": [
            {
                "category": item.category.value,
                "title": item.title,
                "summary": item.summary,
                "url": item.url,
                "source": item.source,
                "tier": item.tier.value,
                "confidence": item.confidence,
            }
            for item in brief.structured_evidence
        ],
        "uncertainty": brief.uncertainty,
    }
    if brief.calibration is not None:
        context["calibration"] = {
            "evidence_quality": brief.calibration.evidence_quality,
            "missing_categories": [
                category.value for category in brief.calibration.missing_categories
            ],
            "risk_flags": brief.calibration.risk_flags,
            "draw_risk": brief.calibration.draw_risk,
            "favorite_bias_risk": brief.calibration.favorite_bias_risk,
        }
    if brief.probability_profile is not None:
        context["probability_profile"] = {
            "home_win": brief.probability_profile.home_win,
            "draw": brief.probability_profile.draw,
            "away_win": brief.probability_profile.away_win,
            "over_2_5": brief.probability_profile.over_2_5,
            "both_teams_to_score": brief.probability_profile.both_teams_to_score,
            "expected_home_goals": brief.probability_profile.expected_home_goals,
            "expected_away_goals": brief.probability_profile.expected_away_goals,
        }
    return (
        "Eres Codex actuando como motor final de prediccion para una polla del Mundial.\n"
        "Usa razonamiento riguroso con toda la evidencia entregada: actualidad deportiva, "
        "alineaciones, lesionados, suplentes, tecnicos, tactica, sede, clima, cancha, "
        "historial, ranking/ELO, cuotas, tabla, incentivos, emociones de mundial y sesgos.\n"
        "Antes del marcador evalua brecha de clase, techo ofensivo, ritmo goleador del torneo, "
        "probabilidad de empate, under/over, ambos anotan, porteros/atajadas, balon parado, "
        "logistica, varianza de debut y sesgo de favorito.\n"
        "Usa la memoria de estado del torneo si existe: forma real tras primera fase, goles a "
        "favor/en contra, ataques calientes, defensas vulnerables, tendencia de partidos abiertos "
        "o cerrados y si el equipo ya mostro BTTS/clean sheet.\n"
        "Prioriza evidencia estructurada con mayor tier/confidence y degrada fuentes genericas, "
        "duplicadas, viejas o contradictorias.\n"
        "La seccion calibration es obligatoria: si draw_risk o favorite_bias_risk son altos, "
        "no uses marcadores comodos del favorito sin justificar datos de calidad de tiro, "
        "portero, balon parado y conversion.\n"
        "Usa probability_profile como baseline numerico: primero decide 1X2/empate, "
        "over/under, ambos anotan y goles esperados; despues deriva el marcador exacto.\n"
        "No conviertas incertidumbre general en empate por defecto. Usa empate solo si hay "
        "evidencia concreta de mercado de empate, perfil under, bloque bajo, porteros fuertes "
        "o baja conversion. Si ranking/mercado/forma alinean a un favorito y hay techo ofensivo, "
        "prefiere victoria por 1-2 goles aunque existan gaps secundarios.\n"
        "El hedge no es empate automatico: usalo como segunda boleta de portafolio. "
        "Si primary favorece a un equipo y over/BTTS estan altos, hedge debe preservar ganador "
        "con otro total o margen. Usa empate como hedge solo cuando el empate compite de verdad "
        "con el favorito o cuando BTTS/over extremo justifica un 2-2.\n"
        "Si faltan fuentes externas, genera un plan de investigacion interno en rationale: "
        "alineaciones, lesionados/sancionados, jugador diferencial, portero, mercado, clima/sede, "
        "estado de grupo, senales de favorito, partido cerrado/abierto y "
        "marcador-bucket probable.\n"
        "No inventes hechos no soportados; si falta informacion, reflejalo en confidence.\n"
        "Devuelve SOLO JSON valido, sin markdown, con este esquema exacto:\n"
        "{"
        '"primary":{"home":0,"away":0},'
        '"hedge":{"home":0,"away":0},'
        '"confidence":0.0,'
        '"rationale":["razon 1","razon 2"],'
        '"risk_flags":["riesgo 1"],'
        '"evidence_gaps":["gap 1"]'
        "}\n"
        "Reglas: goles enteros entre 0 y 9; confidence entre 0 y 1; primary es el marcador "
        "a guardar en GolPredictor; hedge es alternativa si se busca cubrir riesgo.\n"
        f"MEMORIA_APRENDIZAJE:\n{learning_memory or 'Sin memoria aun.'}\n"
        f"CONTEXTO_JSON:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


def _prediction_from_payload(brief: ResearchBrief, payload: dict[str, object]) -> Prediction:
    primary = _scoreline_from_payload(payload.get("primary"))
    hedge = _scoreline_from_payload(payload.get("hedge"))
    confidence_raw = payload.get("confidence")
    if not isinstance(confidence_raw, int | float):
        raise CodexPredictionError("confidence missing or not numeric")
    confidence = max(0.0, min(1.0, float(confidence_raw)))
    rationale = _string_list(payload.get("rationale"))
    risk_flags = _string_list(payload.get("risk_flags"))
    evidence_gaps = _string_list(payload.get("evidence_gaps"))
    if risk_flags:
        rationale.append("Riesgos: " + "; ".join(risk_flags))
    if evidence_gaps:
        rationale.append("Gaps de evidencia: " + "; ".join(evidence_gaps))
    return Prediction(
        match=brief.match,
        primary=primary,
        hedge=hedge,
        confidence=round(confidence, 2),
        rationale=["Codex CLI prediction engine.", *rationale],
        probabilities=brief.probability_profile,
    )


def _scoreline_from_payload(value: object) -> Scoreline:
    if not isinstance(value, dict):
        raise CodexPredictionError("scoreline missing or invalid")
    home = value.get("home")
    away = value.get("away")
    if not isinstance(home, int) or not isinstance(away, int):
        raise CodexPredictionError("scoreline goals must be integers")
    if home > 9 or away > 9:
        raise CodexPredictionError("scoreline goals out of accepted range")
    return Scoreline(home=home, away=away)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _extract_json_object(output: str) -> dict[str, object]:
    stripped = output.strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    matches = re.findall(r"\{(?:.|\n)*\}", stripped)
    for candidate in reversed(matches):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise CodexPredictionError("no JSON object found in Codex output")
