"""Redact sensitive values before any text leaves the machine.

Every detector validates its match (Luhn, IBAN mod-97, AHV EAN-13 checksum) so that
quote numbers and VAT IDs are not destroyed by over-eager patterns. Matches become
typed placeholders such as [CARD_1]; the same value always gets the same placeholder
within one email, and the mapping stays in the local database.
"""

import re
from dataclasses import dataclass, field

# Lengths for the IBAN countries this customer is likely to see; others use 15..34.
_IBAN_LENGTHS = {
    "CH": 21, "LI": 21, "DE": 22, "AT": 20, "FR": 27, "IT": 27, "NL": 18, "BE": 16,
    "GB": 22, "ES": 24, "NO": 15, "EE": 20, "LU": 20, "DK": 18, "SE": 24, "PL": 28,
}  # fmt: skip

_CARD = re.compile(r"(?<![\w-])(?:\d[ -]?){12,18}\d(?![\w-])")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
_AHV = re.compile(r"\b756[.\s]?\d{4}[.\s]?\d{4}[.\s]?\d{2}\b")
_CREDENTIAL = re.compile(
    r"(?i)\b(password|passwort|kennwort|pwd|pin|api[ _-]?key|secret|token|zugangsdaten)"
    r"(\s*[:=]\s*)(\S+)"
)
_KEY_SHAPES = re.compile(
    r"\b(sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}|xox[abp]-[A-Za-z0-9-]{10,})"
)


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def iban_ok(candidate: str) -> bool:
    iban = candidate.replace(" ", "").upper()
    expected = _IBAN_LENGTHS.get(iban[:2])
    if expected is not None and len(iban) != expected:
        return False
    if not 15 <= len(iban) <= 34:
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


def ahv_ok(candidate: str) -> bool:
    digits = re.sub(r"\D", "", candidate)
    if len(digits) != 13 or not digits.startswith("756"):
        return False
    body, check = digits[:12], int(digits[12])
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body))
    return (10 - total % 10) % 10 == check


@dataclass
class Redactor:
    """Holds the placeholder mapping for one email across all of its text sections."""

    mapping: dict[str, str] = field(default_factory=dict)  # original -> placeholder
    kinds: dict[str, str] = field(default_factory=dict)  # placeholder -> kind
    _counters: dict[str, int] = field(default_factory=dict)

    def _placeholder(self, kind: str, original: str) -> str:
        key = re.sub(r"\s", "", original)
        if key in self.mapping:
            return self.mapping[key]
        self._counters[kind] = self._counters.get(kind, 0) + 1
        ph = f"[{kind}_{self._counters[kind]}]"
        self.mapping[key] = ph
        self.kinds[ph] = kind
        return ph

    def redact(self, text: str) -> str:
        def card(m: re.Match) -> str:
            digits = re.sub(r"\D", "", m.group(0))
            if 13 <= len(digits) <= 19 and digits[0] in "23456" and luhn_ok(digits):
                return self._placeholder("CARD", m.group(0))
            return m.group(0)

        def iban(m: re.Match) -> str:
            return self._placeholder("IBAN", m.group(0)) if iban_ok(m.group(0)) else m.group(0)

        def ahv(m: re.Match) -> str:
            return self._placeholder("AHV", m.group(0)) if ahv_ok(m.group(0)) else m.group(0)

        def credential(m: re.Match) -> str:
            return m.group(1) + m.group(2) + self._placeholder("SECRET", m.group(3))

        def key_shape(m: re.Match) -> str:
            return self._placeholder("SECRET", m.group(0))

        text = _IBAN.sub(iban, text)
        text = _AHV.sub(ahv, text)
        text = _CARD.sub(card, text)
        text = _CREDENTIAL.sub(credential, text)
        text = _KEY_SHAPES.sub(key_shape, text)
        return text

    def items(self) -> list[tuple[str, str, str]]:
        """(kind, placeholder, original) for every redacted value."""
        return [(self.kinds[ph], ph, orig) for orig, ph in self.mapping.items()]
