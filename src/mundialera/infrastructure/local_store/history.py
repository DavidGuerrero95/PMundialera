from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from mundialera.domain.models import (
    Prediction,
    PredictionOutcome,
    PredictionRecord,
    ProbabilityProfile,
    Scoreline,
    SubmissionResult,
)
from mundialera.domain.ports import PredictionHistory, PredictionRecorder


class JsonlPredictionStore(PredictionRecorder, PredictionHistory):
    def __init__(self, base_dir: Path, *, timezone_name: str) -> None:
        self._base_dir = base_dir
        self._timezone = ZoneInfo(timezone_name)
        self._predictions_path = base_dir / "predictions.jsonl"
        self._outcomes_path = base_dir / "outcomes.jsonl"
        self._learning_path = base_dir / "learning-memory.md"
        self._tournament_state_path = base_dir / "tournament-state.md"
        self._base_dir.mkdir(parents=True, exist_ok=True)

    @property
    def learning_path(self) -> Path:
        return self._learning_path

    @property
    def tournament_state_path(self) -> Path:
        return self._tournament_state_path

    def record_prediction(
        self,
        prediction: Prediction,
        submission: SubmissionResult,
    ) -> None:
        match = prediction.match
        record = PredictionRecord(
            record_id=str(uuid.uuid4()),
            created_at=datetime.now(self._timezone),
            group=match.group or "",
            match_id=match.match_id,
            match_label=match.label,
            kickoff=match.kickoff,
            primary=prediction.primary,
            hedge=prediction.hedge,
            submitted_scoreline=submission.scoreline,
            confidence=prediction.confidence,
            rationale=prediction.rationale,
            submitted=submission.submitted,
            dry_run=submission.dry_run,
            submission_message=submission.message,
            probabilities=prediction.probabilities,
            decision_flags=prediction.decision_flags,
        )
        self._append_json(self._predictions_path, _record_to_json(record))

    def record_outcomes(self, outcomes: list[PredictionOutcome]) -> int:
        known = {item.record_id for item in self.load_outcomes()}
        new_items = [item for item in outcomes if item.record_id not in known]
        for item in new_items:
            self._append_json(self._outcomes_path, _outcome_to_json(item))
        return len(new_items)

    def load_prediction_records(self) -> list[PredictionRecord]:
        return [_record_from_json(item) for item in self._read_jsonl(self._predictions_path)]

    def load_outcomes(self) -> list[PredictionOutcome]:
        return [_outcome_from_json(item) for item in self._read_jsonl(self._outcomes_path)]

    def load_learning_memory(self) -> str:
        if not self._learning_path.exists():
            return ""
        return self._learning_path.read_text(encoding="utf-8").strip()

    def write_learning_memory(self, content: str) -> None:
        self._learning_path.write_text(content.strip() + "\n", encoding="utf-8")

    def load_tournament_state_memory(self) -> str:
        if not self._tournament_state_path.exists():
            return ""
        return self._tournament_state_path.read_text(encoding="utf-8").strip()

    def write_tournament_state_memory(self, content: str) -> None:
        self._tournament_state_path.write_text(content.strip() + "\n", encoding="utf-8")

    @staticmethod
    def _append_json(path: Path, payload: dict[str, object]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, object]]:
        if not path.exists():
            return []
        items: list[dict[str, object]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                parsed = json.loads(stripped)
                if isinstance(parsed, dict):
                    items.append(parsed)
        return items


def _record_to_json(record: PredictionRecord) -> dict[str, object]:
    payload = asdict(record)
    payload["created_at"] = record.created_at.isoformat()
    payload["kickoff"] = record.kickoff.isoformat() if record.kickoff else None
    return payload


def _record_from_json(payload: dict[str, object]) -> PredictionRecord:
    submitted_scoreline = payload.get("submitted_scoreline", payload["primary"])
    return PredictionRecord(
        record_id=str(payload["record_id"]),
        created_at=datetime.fromisoformat(str(payload["created_at"])),
        group=str(payload["group"]),
        match_id=str(payload["match_id"]),
        match_label=str(payload["match_label"]),
        kickoff=_optional_datetime(payload.get("kickoff")),
        primary=_score_from_json(payload["primary"]),
        hedge=_score_from_json(payload["hedge"]),
        submitted_scoreline=_score_from_json(submitted_scoreline),
        confidence=_float(payload["confidence"]),
        rationale=[str(item) for item in _list(payload.get("rationale", []))],
        submitted=bool(payload["submitted"]),
        dry_run=bool(payload["dry_run"]),
        submission_message=str(payload["submission_message"]),
        probabilities=_probabilities_from_json(payload.get("probabilities")),
        decision_flags=[str(item) for item in _list(payload.get("decision_flags", []))],
    )


def _outcome_to_json(outcome: PredictionOutcome) -> dict[str, object]:
    payload = asdict(outcome)
    payload["settled_at"] = outcome.settled_at.isoformat()
    return payload


def _outcome_from_json(payload: dict[str, object]) -> PredictionOutcome:
    return PredictionOutcome(
        record_id=str(payload["record_id"]),
        settled_at=datetime.fromisoformat(str(payload["settled_at"])),
        group=str(payload["group"]),
        match_id=str(payload["match_id"]),
        match_label=str(payload["match_label"]),
        predicted=_score_from_json(payload["predicted"]),
        actual=_score_from_json(payload["actual"]),
        points=_optional_int(payload.get("points")),
        exact_ok=bool(payload["exact_ok"]),
        winner_ok=bool(payload["winner_ok"]),
        home_goals_ok=bool(payload["home_goals_ok"]),
        away_goals_ok=bool(payload["away_goals_ok"]),
        goal_diff_ok=bool(payload["goal_diff_ok"]),
    )


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(str(value))


def _score_from_json(value: object) -> Scoreline:
    if not isinstance(value, dict):
        msg = "Invalid scoreline JSON"
        raise ValueError(msg)
    return Scoreline(home=int(value["home"]), away=int(value["away"]))


def _probabilities_from_json(value: object) -> ProbabilityProfile | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        msg = "Invalid probability profile JSON"
        raise ValueError(msg)
    return ProbabilityProfile(
        home_win=_float(value["home_win"]),
        draw=_float(value["draw"]),
        away_win=_float(value["away_win"]),
        over_2_5=_float(value["over_2_5"]),
        both_teams_to_score=_float(value["both_teams_to_score"]),
        expected_home_goals=_float(value["expected_home_goals"]),
        expected_away_goals=_float(value["expected_away_goals"]),
    )


def _float(value: object) -> float:
    if not isinstance(value, int | float | str):
        msg = "Invalid float value"
        raise ValueError(msg)
    return float(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int | float | str):
        msg = "Invalid int value"
        raise ValueError(msg)
    return int(value)


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return cast(list[object], value)
