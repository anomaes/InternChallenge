"""Turn a relative delivery phrase into a *suggested* date, computed from the email
date. Suggestions are never used as the delivery date until the clerk confirms one."""

import calendar
import re
from datetime import date, timedelta

_MONTHS = {
    "januar": 1, "january": 1, "jan": 1, "februar": 2, "february": 2, "feb": 2,
    "maerz": 3, "märz": 3, "march": 3, "april": 4, "apr": 4, "mai": 5, "may": 5,
    "juni": 6, "june": 6, "jun": 6, "juli": 7, "july": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9, "oktober": 10, "october": 10, "okt": 10, "oct": 10,
    "november": 11, "nov": 11, "dezember": 12, "december": 12, "dez": 12, "dec": 12,
}  # fmt: skip
_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "eight": 8, "ten": 10,
    "ein": 1, "einer": 1, "zwei": 2, "drei": 3, "vier": 4, "fuenf": 5, "fünf": 5, "sechs": 6,
    "acht": 8, "zehn": 10,
}  # fmt: skip
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))


def _last_day(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def _year_for(month: int, ref: date) -> int:
    return ref.year + 1 if month < ref.month else ref.year


def suggest_delivery_date(text: str | None, ref: date | None) -> tuple[date, str] | None:
    """Return (date, explanation) or None if the phrase isn't understood."""
    if not text or ref is None:
        return None
    t = text.casefold()

    if m := re.search(r"(\d{4})-(\d{2})-(\d{2})", t):
        try:
            return date(int(m[1]), int(m[2]), int(m[3])), "date stated"
        except ValueError:
            pass
    if m := re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", t):
        try:
            return date(int(m[3]), int(m[2]), int(m[1])), "date stated"
        except ValueError:
            pass

    if re.search(r"(ende|end of|end)\s+(des\s+)?(monat|monats|month|this month|the month)", t):
        return _last_day(ref.year, ref.month), f"end of the email's month ({ref:%B %Y})"

    qual = r"(?P<q>ende|end of|end|mitte|mid|middle of|anfang|beginning of|start of|early|bis|by|until)"
    if m := re.search(rf"{qual}[\s-]+(?P<m>{_MONTH_RE})\b(?:\s+(?P<y>\d{{4}}))?", t):
        month = _MONTHS[m["m"]]
        year = int(m["y"]) if m["y"] else _year_for(month, ref)
        q = m["q"]
        if q in ("ende", "end of", "end", "bis", "by", "until"):
            return _last_day(year, month), f"last day of {calendar.month_name[month]} {year}"
        if q in ("mitte", "mid", "middle of"):
            return date(year, month, 15), f"15th of {calendar.month_name[month]} {year}"
        return date(year, month, 1), f"first day of {calendar.month_name[month]} {year}"

    if m := re.search(r"\b(?:kw|woche|week|wk|kalenderwoche)\s*(\d{1,2})\b", t):
        week = int(m[1])
        year = ref.year if week >= ref.isocalendar().week else ref.year + 1
        try:
            return date.fromisocalendar(year, week, 1), f"Monday of week {week}"
        except ValueError:
            return None

    num = r"(\d+|" + "|".join(_NUMBERS) + ")"
    if m := re.search(
        rf"(?:innerhalb|within|in)\s+(?:der\s+naechsten\s+|der\s+nächsten\s+|the\s+next\s+)?{num}\s+(wochen|weeks|tage|tagen|days)",
        t,
    ):
        n = int(m[1]) if m[1].isdigit() else _NUMBERS[m[1]]
        days = n * 7 if m[2] in ("wochen", "weeks") else n
        return ref + timedelta(days=days), f"{n} {m[2]} after the email date"

    if re.search(r"\b(this week|diese woche|diese wo)\b", t):
        return ref + timedelta(
            days=4 - ref.weekday() if ref.weekday() <= 4 else 0
        ), "Friday of the email's week"
    return None
