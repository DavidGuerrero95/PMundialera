from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class GroupName(StrEnum):
    MUNDIAL_COREX = "Mundial CoreX"
    MUNDIAL_FIFA_2026 = "Mundial FIFA 2026"


class EvidenceCategory(StrEnum):
    AVAILABILITY = "availability"
    FORM = "form"
    TACTICS = "tactics"
    VENUE_WEATHER = "venue_weather"
    RANKING = "ranking"
    MARKET = "market"
    REFEREE_DISCIPLINE = "referee_discipline"
    REST_TRAVEL = "rest_travel"
    TABLE_INCENTIVES = "table_incentives"
    GOALKEEPERS_DEFENSE = "goalkeepers_defense"
    SET_PIECES = "set_pieces"
    PLAYER_CONTEXT = "player_context"
    RECENT_MATCH_STATS = "recent_match_stats"
    NEWS = "news"


class SourceTier(StrEnum):
    OFFICIAL = "official"
    RECOGNIZED_MEDIA = "recognized_media"
    AGGREGATOR = "aggregator"
    GENERIC_WEB = "generic_web"


@dataclass(frozen=True, slots=True)
class Team:
    name: str


@dataclass(frozen=True, slots=True)
class Scoreline:
    home: int
    away: int

    def __post_init__(self) -> None:
        if self.home < 0 or self.away < 0:
            msg = "Score values must be greater than or equal to zero"
            raise ValueError(msg)

    def label(self) -> str:
        return f"{self.home} - {self.away}"


@dataclass(frozen=True, slots=True)
class PredictionFormRef:
    form_action: str
    home_field: str
    away_field: str
    submit_field: str | None = None


@dataclass(frozen=True, slots=True)
class Match:
    match_id: str
    kickoff: datetime | None
    home: Team
    away: Team
    group: str | None = None
    prediction: Scoreline | None = None
    result: Scoreline | None = None
    points: int | None = None
    detail_url: str | None = None
    prediction_form: PredictionFormRef | None = None

    @property
    def label(self) -> str:
        return f"{self.home.name} - {self.away.name}"


@dataclass(frozen=True, slots=True)
class ResearchBrief:
    match: Match
    evidence: list[str] = field(default_factory=list)
    structured_evidence: list[EvidenceItem] = field(default_factory=list)
    uncertainty: list[str] = field(default_factory=list)
    calibration: PredictionCalibration | None = None
    probability_profile: ProbabilityProfile | None = None


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    category: EvidenceCategory
    title: str
    summary: str
    url: str
    source: str
    tier: SourceTier
    confidence: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            msg = "Evidence confidence must be between 0.0 and 1.0"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class PredictionCalibration:
    evidence_quality: float
    missing_categories: list[EvidenceCategory] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    draw_risk: float = 0.0
    favorite_bias_risk: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.evidence_quality <= 1.0:
            msg = "Evidence quality must be between 0.0 and 1.0"
            raise ValueError(msg)
        if not 0.0 <= self.draw_risk <= 1.0:
            msg = "Draw risk must be between 0.0 and 1.0"
            raise ValueError(msg)
        if not 0.0 <= self.favorite_bias_risk <= 1.0:
            msg = "Favorite bias risk must be between 0.0 and 1.0"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ProbabilityProfile:
    home_win: float
    draw: float
    away_win: float
    over_2_5: float
    both_teams_to_score: float
    expected_home_goals: float
    expected_away_goals: float

    def __post_init__(self) -> None:
        for name, value in (
            ("home_win", self.home_win),
            ("draw", self.draw),
            ("away_win", self.away_win),
            ("over_2_5", self.over_2_5),
            ("both_teams_to_score", self.both_teams_to_score),
        ):
            if not 0.0 <= value <= 1.0:
                msg = f"{name} must be between 0.0 and 1.0"
                raise ValueError(msg)
        if self.expected_home_goals < 0.0 or self.expected_away_goals < 0.0:
            msg = "Expected goals must be greater than or equal to zero"
            raise ValueError(msg)
        total = self.home_win + self.draw + self.away_win
        if abs(total - 1.0) > 0.02:
            msg = "1X2 probabilities must sum to 1.0"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Prediction:
    match: Match
    primary: Scoreline
    hedge: Scoreline
    confidence: float
    rationale: list[str] = field(default_factory=list)
    probabilities: ProbabilityProfile | None = None
    decision_flags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            msg = "Confidence must be between 0.0 and 1.0"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    match: Match
    scoreline: Scoreline
    submitted: bool
    dry_run: bool
    message: str


@dataclass(frozen=True, slots=True)
class PredictionRecord:
    record_id: str
    created_at: datetime
    group: str
    match_id: str
    match_label: str
    kickoff: datetime | None
    primary: Scoreline
    hedge: Scoreline
    submitted_scoreline: Scoreline
    confidence: float
    rationale: list[str]
    submitted: bool
    dry_run: bool
    submission_message: str
    probabilities: ProbabilityProfile | None = None
    decision_flags: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ResearchRecord:
    record_id: str
    created_at: datetime
    group: str
    match_id: str
    match_label: str
    kickoff: datetime | None
    home_team: str
    away_team: str
    evidence: list[str]
    structured_evidence: list[EvidenceItem]
    uncertainty: list[str]
    calibration: PredictionCalibration | None = None
    probabilities: ProbabilityProfile | None = None
    analysis_dimensions: dict[str, list[str]] = field(default_factory=dict)
    star_player_signals: list[str] = field(default_factory=list)
    team_state_signals: list[str] = field(default_factory=list)
    lineup_signals: list[str] = field(default_factory=list)
    bench_rotation_signals: list[str] = field(default_factory=list)
    availability_signals: list[str] = field(default_factory=list)
    player_discipline_signals: list[str] = field(default_factory=list)
    rhythm_signals: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PredictionOutcome:
    record_id: str
    settled_at: datetime
    group: str
    match_id: str
    match_label: str
    predicted: Scoreline
    actual: Scoreline
    points: int | None
    exact_ok: bool
    winner_ok: bool
    home_goals_ok: bool
    away_goals_ok: bool
    goal_diff_ok: bool
