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
    # Picked by running all sample emails against candidate models (scripts/run_all.py).
    extraction_model: str = "gpt-6-luna"
    extraction_reasoning: str = "medium"
    decisions_model: str = "gpt-6-luna"
    llm_timeout_s: float = 120.0

    database_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'app.db'}"
    erp_base_url: str = "http://127.0.0.1:8080"

    master_data_path: Path = REPO_ROOT / "master_data.json"
    sample_emails_dir: Path = REPO_ROOT / "emails"
    # Committed on purpose: the app runs on the sample emails without an API key, and
    # development spend stays near zero. Keys are hashes of the *redacted* model input.
    llm_cache_dir: Path = BACKEND_DIR / "llm_cache"

    # Mail from this domain is internal; anything else (suppliers) is external.
    company_domain: str = "customer.com"
    frontend_base_url: str = "http://localhost:5173"

    def api_key(self) -> str | None:
        if self.openai_api_key is None:
            return None
        return self.openai_api_key.get_secret_value().strip() or None


settings = Settings()
