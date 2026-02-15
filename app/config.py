from pydantic import BaseModel, Field
import os

class Settings(BaseModel):
    absstats_base_url: str = Field(default="http://localhost:3010")
    poll_seconds: int = Field(default=300)
    state_db_path: str = Field(default="/data/state.db")

    achievements_path: str = Field(default="./data/achievements.points.json")
    series_refresh_seconds: int = Field(default=24 * 3600)

    # SMTP
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_username: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_from: str = Field(default="")
    smtp_to_override: str = Field(default="")

    discord_proxy_url: str = Field(default="")

    completed_endpoint: str = Field(default="/api/completed")
    allow_playlist_fallback: bool = Field(default=True)
    send_test_email: bool = Field(default=False)


def load_settings() -> Settings:
    def b(name: str, default: bool) -> bool:
        v = os.getenv(name)
        if v is None:
            return default
        return v.strip().lower() in ("1", "true", "yes", "y", "on")

    return Settings(
        absstats_base_url=os.getenv("ABSSTATS_BASE_URL", "http://localhost:3010").rstrip("/"),
        poll_seconds=int(os.getenv("POLL_SECONDS", "300")),
        state_db_path=os.getenv("STATE_DB_PATH", "/data/state.db"),

        achievements_path=os.getenv("ACHIEVEMENTS_PATH", "./data/achievements.points.json"),
        series_refresh_seconds=int(os.getenv("SERIES_REFRESH_SECONDS", str(24 * 3600))),
        smtp_host=os.getenv("SMTP_HOST", ""),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_username=os.getenv("SMTP_USERNAME", ""),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from=os.getenv("SMTP_FROM", ""),
        smtp_to_override=os.getenv("SMTP_TO_OVERRIDE", ""),
        discord_proxy_url=os.getenv("DISCORD_PROXY_URL", ""),
        completed_endpoint=os.getenv("COMPLETED_ENDPOINT", "/api/completed"),
        allow_playlist_fallback=b("ALLOW_PLAYLIST_FALLBACK", True),
        send_test_email=b("SEND_TEST_EMAIL", False),
    )