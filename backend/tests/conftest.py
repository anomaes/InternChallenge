import os
import tempfile
from pathlib import Path

# Point the app at a throwaway database and cache before anything imports it.
_tmp = Path(tempfile.mkdtemp(prefix="req-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'test.db'}"
# The committed model-response cache: end-to-end tests replay real model output, offline.
os.environ["LLM_CACHE_DIR"] = str(Path(__file__).resolve().parents[1] / "llm_cache")
os.environ["OPENAI_API_KEY"] = ""
os.environ["ERP_BASE_URL"] = "http://127.0.0.1:9"  # nothing listens here

import pytest  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.config import REPO_ROOT  # noqa: E402
from app.db.seed import seed_master_data  # noqa: E402
from app.db.session import create_tables, engine  # noqa: E402
from app.domain.master import MasterData  # noqa: E402

EMAILS = REPO_ROOT / "emails"


@pytest.fixture(scope="session")
def md() -> MasterData:
    create_tables()
    with Session(engine) as s:
        seed_master_data(s, force=True)
        return MasterData.load(s)


@pytest.fixture
def session():
    create_tables()
    with Session(engine) as s:
        seed_master_data(s)
        yield s


def eml(name: str) -> bytes:
    return (EMAILS / name).read_bytes()
