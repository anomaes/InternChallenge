"""On-disk cache of model responses, keyed by a hash of (kind, model, prompt version,
redacted input). Used in "cached" mode so the 48 samples replay without API calls; an
unseen email always misses and goes live."""

import hashlib
import json
from typing import Any

from app.config import settings

# Keys read or written by this process; scripts/run_all.py --prune deletes the rest.
USED: set[str] = set()


def cache_key(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode())
        h.update(b"\x00")
    return h.hexdigest()[:32]


def cache_get(key: str) -> dict[str, Any] | None:
    path = settings.llm_cache_dir / f"{key}.json"
    if not path.exists():
        return None
    USED.add(key)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cache_put(key: str, value: dict[str, Any]) -> None:
    USED.add(key)
    settings.llm_cache_dir.mkdir(parents=True, exist_ok=True)
    path = settings.llm_cache_dir / f"{key}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
