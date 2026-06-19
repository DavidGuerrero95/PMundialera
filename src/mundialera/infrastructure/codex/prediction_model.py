from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import textwrap
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
    star_player_signals = _star_player_signals_from_brief(brief)
    if not star_player_signals:
        star_player_signals = _star_player_signals_from_memory(
            learning_memory,
            match_label=match.label,
        )
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
        "star_player_signals": star_player_signals,
        "expected_analysis_dimensions": [
            "equipos",
            "torneo",
            "jugadores",
            "jugadores_diferenciables",
            "jugadores_estrellas_desequilibrantes",
            "arbitros",
            "faltas_tarjetas",
            "hinchada",
            "sede_cancha_clima",
            "titularidad",
            "suplencia",
            "lesionados_sancionados_convocados",
            "buen_ritmo",
            "mal_ritmo",
            "buen_ataque",
            "mal_ataque",
            "buena_defensa",
            "mala_defensa",
        ],
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
    template = textwrap.dedent(
        """
        # Pronostico GolPredictor

        ## Rol

        Eres Codex actuando como motor final de prediccion para una polla del Mundial.
        Debes producir un marcador exacto primario y un marcador hedge con razonamiento
        probabilistico, calibrado y trazable.

        ## Evidencia que debes evaluar

        Usa razonamiento riguroso con toda la evidencia entregada:

        - actualidad deportiva
        - alineaciones, lesionados, sancionados, suplentes y tecnicos
        - tactica, sistema, duelos, presion y balon parado
        - sede, clima, cancha, viaje y logistica
        - historial, ranking/ELO, cuotas, tabla e incentivos
        - emociones de mundial, varianza de debut y sesgos de favorito
        - porteros, atajadas, centrales, laterales y fragilidad defensiva
        - under/over, ambos anotan, ritmo goleador y techo ofensivo

        ## Dimensiones obligatorias de analisis

        Antes de escoger marcador, revisa y refleja en `rationale` o `evidence_gaps`
        el estado de estas dimensiones cuando existan en el contexto:

        - equipos y estado del torneo
        - jugadores, jugadores diferenciales, noticias personales/profesionales
        - jugadores estrella y desequilibrantes capaces de romper el partido
        - arbitros, faltas, tarjetas, penales y disciplina
        - hinchada, localia, sede, estadio, cancha y clima
        - titularidad, suplencia, rotaciones, convocados, lesionados y sancionados
        - buen ritmo, mal ritmo, partido abierto o partido cerrado
        - buen ataque, mal ataque, buena defensa y mala defensa
        - porteros, centrales, laterales, balon parado y fragilidad defensiva

        ## Jugadores estrella y desequilibrantes

        Trata `star_player_signals` como un dato de alto impacto. Para cada equipo,
        evalua si existe un jugador capaz de alterar el marcador por:

        - remate, xG, asistencias, conduccion o regate
        - balon parado, penales o tiros libres
        - volumen reciente de minutos y estado fisico
        - rol tactico real: titular, suplente revulsivo o ausencia sensible
        - noticias personales/profesionales que afecten foco o disponibilidad

        Si una estrella esta disponible y en buen ritmo, puede justificar subir techo
        ofensivo, BTTS u over. Si falta, llega tocada o no inicia, reduce confianza y
        explicalo en `evidence_gaps` o `risk_flags`.

        ## Memoria de torneo y aprendizaje

        Usa la memoria de estado del torneo si existe:

        - forma real tras primera fase
        - goles a favor/en contra
        - ataques calientes y defensas vulnerables
        - tendencia de partidos abiertos o cerrados
        - senales BTTS, clean sheet, favorito, empate y partido trabado

        ```markdown
        {learning_memory}
        ```

        ## Reglas de decision

        - Prioriza evidencia estructurada con mayor `tier` y `confidence`.
        - Degrada fuentes genericas, duplicadas, viejas o contradictorias.
        - Usa `probability_profile` como baseline numerico antes del marcador exacto.
        - Decide primero 1X2/empate, under/over, ambos anotan y goles esperados.
        - No conviertas incertidumbre general en empate por defecto.
        - Usa empate solo con evidencia concreta: mercado de empate, perfil under,
          bloque bajo, porteros fuertes o baja conversion.
        - Si ranking, mercado, forma y techo ofensivo alinean a un favorito,
          prefiere victoria por 1-2 goles aunque existan gaps secundarios.
        - Si `draw_risk` o `favorite_bias_risk` son altos, no uses marcadores comodos
          del favorito sin justificar calidad de tiro, portero, balon parado y conversion.
        - El hedge no es empate automatico: es una segunda boleta de portafolio.
        - Si `primary` favorece a un equipo y over/BTTS estan altos, el hedge debe
          preservar ganador con otro total o margen.
        - Usa empate como hedge solo cuando compite de verdad con el favorito o cuando
          BTTS/over extremo justifica un 2-2.
        - No inventes hechos no soportados; si falta informacion, reflejalo en `confidence`.

        ## Gaps de evidencia

        Si faltan fuentes externas, genera un plan de investigacion interno en `rationale`
        cubriendo:

        - alineaciones
        - lesionados/sancionados
        - jugador diferencial
        - portero
        - mercado
        - clima/sede
        - estado de grupo
        - senales de favorito
        - partido cerrado/abierto
        - marcador-bucket probable

        ## Formato de salida obligatorio

        Aunque este prompt esta escrito en Markdown, tu respuesta debe ser exclusivamente
        JSON valido, sin Markdown, sin texto adicional y con este esquema exacto:

        ```json
        {{
          "primary": {{"home": 0, "away": 0}},
          "hedge": {{"home": 0, "away": 0}},
          "confidence": 0.0,
          "rationale": ["razon 1", "razon 2"],
          "risk_flags": ["riesgo 1"],
          "evidence_gaps": ["gap 1"]
        }}
        ```

        Reglas de validacion:

        - `home` y `away` deben ser goles enteros entre 0 y 9.
        - `confidence` debe estar entre 0 y 1.
        - `primary` es el marcador a guardar en GolPredictor.
        - `hedge` es la alternativa si se busca cubrir riesgo.

        ## Contexto JSON

        ```json
        {context_json}
        ```
        """
    ).strip()
    return template.format(
        learning_memory=learning_memory or "Sin memoria aun.",
        context_json=json.dumps(context, ensure_ascii=False, indent=2),
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


def _star_player_signals_from_brief(brief: ResearchBrief) -> list[str]:
    terms = (
        "estrella",
        "desequilibrante",
        "desequilibrio",
        "differencemaker",
        "game changer",
        "key player",
        "jugador clave",
        "figura",
    )
    player_signal_terms = (
        "alineación",
        "alineacion",
        "asistencias",
        "atacantes",
        "capitán",
        "capitan",
        "convocados",
        "goleador",
        "goleiro",
        "goles",
        "jugadores",
        "mercado",
        "min.",
        "minutos",
        "penaltis",
        "puntos",
        "sustituciones",
        "titular",
        "valores",
    )
    player_signal_categories = {
        "player_context",
        "availability",
        "tactics",
        "market",
        "news",
        "recent_match_stats",
    }
    signals: list[str] = []
    seen: set[str] = set()

    def add_signal(value: str) -> None:
        normalized_value = value.strip()
        if not normalized_value or normalized_value in seen or len(signals) >= 8:
            return
        signals.append(normalized_value)
        seen.add(normalized_value)

    for item in brief.structured_evidence:
        text = f"{item.category.value}: {item.title}. {item.summary}"
        normalized = text.casefold()
        if item.category.value == "player_context" or (
            item.category.value in player_signal_categories
            and any(term in normalized for term in player_signal_terms)
        ):
            add_signal(text)

    for raw_signal in brief.evidence:
        if any(term in raw_signal.casefold() for term in terms):
            add_signal(raw_signal)

    return signals


def _star_player_signals_from_memory(learning_memory: str, *, match_label: str) -> list[str]:
    signals: list[str] = []
    active_match = False
    match_header = f"- {match_label}:"
    for line in learning_memory.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") and not stripped.startswith("- star_player_signal:"):
            active_match = stripped == match_header
            continue
        if not active_match or "star_player_signal:" not in stripped:
            continue
        _, _, signal = stripped.partition("star_player_signal:")
        normalized_signal = signal.strip()
        if normalized_signal:
            signals.append(normalized_signal)
        if len(signals) >= 8:
            break
    return signals


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
