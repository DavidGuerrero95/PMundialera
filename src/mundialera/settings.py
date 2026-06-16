from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    golpredictor_base_url: str = Field(
        default="https://www.golpredictor.com",
        validation_alias="GOLPREDICTOR_BASE_URL",
    )
    golpredictor_username: str | None = Field(
        default=None,
        validation_alias="GOLPREDICTOR_USERNAME",
    )
    golpredictor_password: SecretStr | None = Field(
        default=None,
        validation_alias="GOLPREDICTOR_PASSWORD",
    )
    golpredictor_groups: str = Field(
        default="Mundial CoreX,Mundial FIFA 2026",
        validation_alias="GOLPREDICTOR_GROUPS",
    )
    golpredictor_hedge_groups: str = Field(
        default="Mundial FIFA 2026",
        validation_alias="GOLPREDICTOR_HEDGE_GROUPS",
    )
    pmundialera_timezone: str = Field(
        default="America/Bogota",
        validation_alias="PMUNDIALERA_TIMEZONE",
    )
    pmundialera_submission_window_minutes: int = Field(
        default=35,
        ge=1,
        le=180,
        validation_alias="PMUNDIALERA_SUBMISSION_WINDOW_MINUTES",
    )
    pmundialera_dry_run: bool = Field(default=True, validation_alias="PMUNDIALERA_DRY_RUN")
    pmundialera_enable_web_research: bool = Field(
        default=True,
        validation_alias="PMUNDIALERA_ENABLE_WEB_RESEARCH",
    )
    pmundialera_max_research_queries: int = Field(
        default=18,
        ge=1,
        le=20,
        validation_alias="PMUNDIALERA_MAX_RESEARCH_QUERIES",
    )
    pmundialera_max_results_per_query: int = Field(
        default=5,
        ge=1,
        le=10,
        validation_alias="PMUNDIALERA_MAX_RESULTS_PER_QUERY",
    )
    pmundialera_enable_page_scrape: bool = Field(
        default=True,
        validation_alias="PMUNDIALERA_ENABLE_PAGE_SCRAPE",
    )
    pmundialera_max_pages_per_query: int = Field(
        default=2,
        ge=0,
        le=5,
        validation_alias="PMUNDIALERA_MAX_PAGES_PER_QUERY",
    )
    pmundialera_max_scraped_chars: int = Field(
        default=1800,
        ge=400,
        le=6000,
        validation_alias="PMUNDIALERA_MAX_SCRAPED_CHARS",
    )
    pmundialera_prediction_engine: str = Field(
        default="codex",
        validation_alias="PMUNDIALERA_PREDICTION_ENGINE",
    )
    pmundialera_codex_executable: str = Field(
        default="codex",
        validation_alias="PMUNDIALERA_CODEX_EXECUTABLE",
    )
    pmundialera_codex_args: str = Field(
        default="exec -",
        validation_alias="PMUNDIALERA_CODEX_ARGS",
    )
    pmundialera_codex_model: str | None = Field(
        default=None,
        validation_alias="PMUNDIALERA_CODEX_MODEL",
    )
    pmundialera_codex_timeout_seconds: int = Field(
        default=300,
        ge=30,
        le=1800,
        validation_alias="PMUNDIALERA_CODEX_TIMEOUT_SECONDS",
    )
    pmundialera_data_dir: str = Field(
        default=".pmundialera",
        validation_alias="PMUNDIALERA_DATA_DIR",
    )

    def configured_groups(self) -> list[str]:
        return [group.strip() for group in self.golpredictor_groups.split(",") if group.strip()]

    def hedge_groups(self) -> set[str]:
        return {
            group.strip().casefold()
            for group in self.golpredictor_hedge_groups.split(",")
            if group.strip()
        }

    def require_golpredictor_credentials(self) -> tuple[str, str]:
        if not self.golpredictor_username or not self.golpredictor_password:
            msg = "GOLPREDICTOR_USERNAME and GOLPREDICTOR_PASSWORD are required"
            raise RuntimeError(msg)
        return self.golpredictor_username, self.golpredictor_password.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
