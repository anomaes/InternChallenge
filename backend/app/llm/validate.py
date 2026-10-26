"""What happens when the model returns garbage.

Layer 1 (API): structured outputs enforce the JSON schema.
Layer 2 (Pydantic, in the SDK): types and required fields.
Layer 3 (here, semantic): positive quantities, ISO currency, sane dates, GL code in
         master data. Errors go back to the model once; whatever is still wrong after
         the retry is dropped (set to null) and surfaces as a missing value.
Layer 4 (here, grounding): every number, ID and quote must be found in the source text
         after normalisation (1'250.00 = 1.250,00 = 1,250.00). A value that can't be
         found is marked `unverified`; on a routing field that blocks.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from rapidfuzz import fuzz

from app.domain.matching import normalise_name
from app.llm.schema import Extraction

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "twenty": 20, "hundred": 100,
    "thousand": 1000, "ein": 1, "eine": 1, "eins": 1, "zwei": 2, "drei": 3, "vier": 4,
    "fünf": 5, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
    "elf": 11, "zwölf": 12, "zwoelf": 12, "zwanzig": 20, "hundert": 100, "tausend": 1000,
    "dozen": 12, "dutzend": 12,
}  # fmt: skip
_TOKEN = re.compile(r"\d[\d'’.,]*\d|\d")


def _interpret(token: str) -> set[Decimal]:
    t = token.replace("’", "'").strip(".,'")
    if not t:
        return set()
    out: set[Decimal] = set()
    try:
        if "'" in t:
            t2 = t.replace("'", "")
            return _interpret(t2) if t2 != t else out
        dots, commas = t.count("."), t.count(",")
        if dots and commas:
            dec = "." if t.rfind(".") > t.rfind(",") else ","
            thou = "," if dec == "." else "."
            out.add(Decimal(t.replace(thou, "").replace(dec, ".")))
        elif dots or commas:
            sep = "." if dots else ","
            if t.count(sep) > 1:
                out.add(Decimal(t.replace(sep, "")))
            else:
                head, tail = t.split(sep)
                if len(tail) == 3:
                    out.add(Decimal(head + tail))  # thousands separator
                out.add(Decimal(f"{head}.{tail}"))  # decimal separator
        else:
            out.add(Decimal(t))
    except InvalidOperation:
        pass
    return out


def numbers_in(text: str) -> set[Decimal]:
    nums: set[Decimal] = set()
    for m in _TOKEN.finditer(text):
        nums |= _interpret(m.group(0))
    lowered = text.casefold()
    for word, n in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", lowered):
            nums.add(Decimal(n))
    return nums


def _dec(value: float) -> Decimal:
    return Decimal(str(value))


def _alnum(s: str) -> str:
    return re.sub(r"[^0-9a-z]", "", s.casefold())


def _ws(s: str) -> str:
    return " ".join(s.split()).casefold()


def parse_iso(value: str | None) -> date | None:
    if not value:
        return None
    try:
        d = date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None
    return d if 2000 <= d.year <= 2100 else None


def date_in_source(d: date, source: str) -> bool:
    forms = {
        d.isoformat(),
        f"{d.day:02d}.{d.month:02d}.{d.year}",
        f"{d.day}.{d.month}.{d.year}",
        f"{d.day:02d}/{d.month:02d}/{d.year}",
        f"{d.day}. {d:%B} {d.year}",
        f"{d.day} {d:%B} {d.year}",
        f"{d:%B} {d.day}, {d.year}",
    }
    low = source.casefold()
    return any(f.casefold() in low for f in forms)


# --------------------------------------------------------------------------- semantic


def semantic_errors(x: Extraction, gl_codes: set[str]) -> list[str]:
    errs: list[str] = []
    if x.currency is not None and not re.fullmatch(r"[A-Z]{3}", x.currency):
        errs.append(f"currency must be an ISO 4217 code like CHF or EUR, got {x.currency!r}")
    for i, ln in enumerate(x.line_items, start=1):
        if not ln.description.strip():
            errs.append(f"line_items[{i}].description is empty")
        if ln.quantity is not None and ln.kind != "discount" and ln.quantity <= 0:
            errs.append(f"line_items[{i}].quantity must be positive, got {ln.quantity}")
        if ln.unit_price is not None and ln.kind != "discount" and ln.unit_price < 0:
            errs.append(f"line_items[{i}].unit_price is negative but kind is {ln.kind}")
        if ln.price_basis is not None and ln.price_basis <= 0:
            errs.append(f"line_items[{i}].price_basis must be positive")
    for name in ("delivery_date_iso", "quote_date_iso", "quote_valid_until_iso"):
        v = getattr(x, name)
        if v is not None and parse_iso(v) is None:
            errs.append(f"{name} must be a real date in YYYY-MM-DD, got {v!r}")
    if x.gl_account_suggestion is not None and x.gl_account_suggestion not in gl_codes:
        errs.append(
            f"gl_account_suggestion {x.gl_account_suggestion!r} is not one of the listed codes"
        )
    if x.vat_rate_percent is not None and not 0 <= x.vat_rate_percent <= 30:
        errs.append(f"vat_rate_percent {x.vat_rate_percent} is not a plausible VAT rate")
    return errs


def drop_invalid(x: Extraction, gl_codes: set[str]) -> tuple[Extraction, list[str]]:
    """After the retry: null out whatever still fails, so it surfaces as missing."""
    dropped: list[str] = []
    data = x.model_copy(deep=True)
    if data.currency is not None and not re.fullmatch(r"[A-Z]{3}", data.currency):
        data.currency = None
        dropped.append("currency")
    for name in ("delivery_date_iso", "quote_date_iso", "quote_valid_until_iso"):
        if getattr(data, name) is not None and parse_iso(getattr(data, name)) is None:
            setattr(data, name, None)
            dropped.append(name)
    if data.gl_account_suggestion is not None and data.gl_account_suggestion not in gl_codes:
        data.gl_account_suggestion = None
        dropped.append("gl_account_suggestion")
    for i, ln in enumerate(data.line_items, start=1):
        if ln.quantity is not None and ln.kind != "discount" and ln.quantity <= 0:
            ln.quantity = None
            dropped.append(f"line_items[{i}].quantity")
        if ln.unit_price is not None and ln.kind != "discount" and ln.unit_price < 0:
            ln.unit_price = None
            dropped.append(f"line_items[{i}].unit_price")
        if ln.price_basis is not None and ln.price_basis <= 0:
            ln.price_basis = None
            dropped.append(f"line_items[{i}].price_basis")
    if data.vat_rate_percent is not None and not 0 <= data.vat_rate_percent <= 30:
        data.vat_rate_percent = None
        dropped.append("vat_rate_percent")
    return data, dropped


# --------------------------------------------------------------------------- grounding


def ground(x: Extraction, source: str) -> dict[str, str]:
    """Return {field path: reason} for every value that can't be found in the source."""
    nums = numbers_in(source)
    alnum_source = _alnum(source)
    ws_source = _ws(source)
    norm_source = normalise_name(source)
    bad: dict[str, str] = {}

    def num(path: str, value: float | None) -> None:
        if value is None:
            return
        d = _dec(value)
        if d not in nums and abs(d) not in nums:
            bad[path] = f"{value:g} does not appear in the email or attachments"

    def ident(path: str, value: str | None) -> None:
        if value and _alnum(value) and _alnum(value) not in alnum_source:
            bad[path] = f'"{value}" does not appear in the email or attachments'

    def quote(path: str, value: str | None) -> None:
        if value and _ws(value) not in ws_source:
            bad[path] = "evidence quote not found verbatim in the source"

    for i, ln in enumerate(x.line_items, start=1):
        p = f"line.{i}"
        num(f"{p}.quantity", ln.quantity)
        num(f"{p}.unit_price", ln.unit_price)
        num(f"{p}.stated_line_total", ln.stated_line_total)
        if ln.price_basis not in (None, 1):
            num(f"{p}.price_basis", ln.price_basis)
        ident(f"{p}.item_code", ln.item_code)
        quote(f"{p}.source_quote", ln.source_quote)
    for i, st in enumerate(x.stated_totals):
        if not st.is_approximate:  # "around five thousand" is never used for routing
            num(f"stated_totals.{i}", st.amount)
    num("vat_amount", x.vat_amount)
    num("vat_rate", x.vat_rate_percent)

    ident("supplier_vat", x.supplier_vat_id)
    ident("cost_center", x.cost_center_code)
    for ref in x.referenced_requests:
        ident("referenced_requests", ref)
    if x.supplier_name:
        n = normalise_name(x.supplier_name)
        if n and n not in norm_source and fuzz.partial_ratio(n, norm_source) < 90:
            bad["supplier"] = f'"{x.supplier_name}" does not appear in the email or attachments'
    quote("supplier_quote", x.supplier_name_quote)
    quote("cost_center_quote", x.cost_center_quote)
    quote("prior_approval_quote", x.prior_approval_quote)
    if x.currency and x.currency.casefold() not in source.casefold():
        symbols = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "fr."}
        if symbols.get(x.currency, "\x00") not in source:
            bad["currency"] = f"{x.currency} does not appear in the source"

    for name, path in (
        ("delivery_date_iso", "delivery_date"),
        ("quote_valid_until_iso", "quote_valid_until"),
        ("quote_date_iso", "quote_date"),
    ):
        d = parse_iso(getattr(x, name))
        if d and not date_in_source(d, source):
            bad[path] = f"{d.isoformat()} is not written as a date in the source"
    return bad
