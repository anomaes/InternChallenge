from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Process configuration, read from the environment and the repo-root .env.

    Runtime switches the user flips in the UI (e.g. decision checks) live in the
    database instead, so they survive restarts and need no redeploy.
    """

    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    openai_api_key: SecretStr | None = None
    # Picked in phase 3 by running all sample emails against candidate models.
    extraction_model: str | None = None
    decisions_model: str = "gpt-6-luna"

    database_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'app.db'}"
    erp_base_url: str = "http://127.0.0.1:8080"

    master_data_path: Path = REPO_ROOT / "master_data.json"
    sample_emails_dir: Path = REPO_ROOT / "emails"


settings = Settings()
