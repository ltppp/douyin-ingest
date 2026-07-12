from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from project.paths import default_runtime_root

ROOT_DIR = default_runtime_root()


class Settings(BaseModel):
    """Central runtime configuration."""

    model_config = ConfigDict(frozen=True)

    home_url: str = "https://www.douyin.com/"
    storage_state_path: Path = ROOT_DIR / "storage" / "storage_state.json"
    output_path: Path = ROOT_DIR / "output" / "result.json"
    debug_dir: Path = ROOT_DIR / "output" / "debug"
    log_path: Path = ROOT_DIR / "logs" / "crawler.log"

    login_timeout_seconds: float = Field(default=300.0, gt=0)
    capture_timeout_seconds: float = Field(default=45.0, gt=0)
    navigation_timeout_ms: float = Field(default=60_000.0, gt=0)
    page_settle_seconds: float = Field(default=3.0, ge=0)
    response_drain_timeout_seconds: float = Field(default=2.0, gt=0)

    request_timeout_seconds: float = Field(default=20.0, gt=0)
    request_retries: int = Field(default=3, ge=0)
    retry_backoff_seconds: float = Field(default=1.0, ge=0)
    page_delay_min_seconds: float = Field(default=0.4, ge=0)
    page_delay_max_seconds: float = Field(default=0.9, ge=0)
    max_pages: int = Field(default=10_000, gt=0)
    response_sample_items: int = Field(default=3, gt=0)

    browser_headless: bool = False
    auth_cookie_names: tuple[str, ...] = (
        "sessionid",
        "sessionid_ss",
        "sid_guard",
        "uid_tt",
        "uid_tt_ss",
    )

    @model_validator(mode="after")
    def validate_page_delay(self) -> Settings:
        if self.page_delay_max_seconds < self.page_delay_min_seconds:
            raise ValueError("page_delay_max_seconds 不能小于 page_delay_min_seconds")
        return self

    def ensure_directories(self) -> None:
        for path in (
            self.storage_state_path.parent,
            self.output_path.parent,
            self.debug_dir,
            self.log_path.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)


DEFAULT_SETTINGS = Settings()
