"""Runtime switches flipped from the Settings & demo page, persisted in the database."""

from typing import Any

from sqlmodel import Session

from app.db.models import AppSetting

DEFAULTS: dict[str, Any] = {
    "decision_checks_enabled": False,
    # Probability thresholds for the decision checks, tuned with scripts/run_all.py --checks:
    # every correct value in the samples scored >= 0.86, planted errors <= 0.17.
    "check_high": 0.80,
    "check_low": 0.50,
    # cached: reuse a stored model response for an identical (redacted) input; live: always call.
    "llm_cache_mode": "cached",
}


def get_setting(session: Session, key: str) -> Any:
    row = session.get(AppSetting, key)
    return DEFAULTS.get(key) if row is None else row.value


def all_settings(session: Session) -> dict[str, Any]:
    return {k: get_setting(session, k) for k in DEFAULTS}


def set_setting(session: Session, key: str, value: Any) -> None:
    if key not in DEFAULTS:
        raise KeyError(key)
    row = session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
    else:
        row.value = value
        session.add(row)
