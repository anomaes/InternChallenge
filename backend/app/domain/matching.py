"""Match what the document says against master data (brief section 6).

Suppliers: VAT ID first (unambiguous), then the name in three tiers. Look-alikes exist
(Acme Bearings GmbH / ACME Bearing Group Ltd, Müller Industriebedarf / Mueller
Industriebedarf AG), so a tier only counts if it yields exactly one supplier:

  1. exact name (case-insensitive, umlauts transliterated, punctuation ignored)
  2. exact name without legal form (GmbH, AG, Ltd, ...)
  3. fuzzy: never accepted on its own; offered to the clerk as a candidate

Cost centers: exact code only. "CC 1002" is the same code written differently; CC-9100
is not "close to" anything, it is unknown.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from app.db.models import CostCenter, Employee, Supplier
from app.domain.issues import Finding

_LEGAL_FORMS = {
    "gmbh", "ag", "kg", "ltd", "limited", "inc", "incorporated", "bv", "nv", "as", "asa", "srl",
    "spa", "ou", "oy", "ab", "sa", "sarl", "llc", "plc", "se", "co", "corp", "gesmbh", "ohg",
}  # fmt: skip
_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def normalise_name(name: str) -> str:
    s = name.casefold().translate(_TRANSLIT)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def strip_legal_form(norm: str) -> str:
    tokens = norm.split()
    # "S.r.l." normalises to "s r l"; glue single letters back together first.
    glued: list[str] = []
    for t in tokens:
        if len(t) == 1 and glued and len(glued[-1]) <= 2 and glued[-1].isalpha() and t.isalpha():
            glued[-1] += t
        else:
            glued.append(t)
    return " ".join(t for t in glued if t not in _LEGAL_FORMS)


def normalise_vat(vat: str) -> str:
    s = re.sub(r"[^A-Z0-9]", "", vat.upper())
    s = re.sub(r"(MWST|TVA|IVA|VAT)$", "", s)
    s = re.sub(r"^(VAT|UID|USTIDNR|UST)", "", s)
    return s


@dataclass
class SupplierMatch:
    supplier_id: str | None
    method: str | None  # vat | name_exact | clerk
    candidates: list[dict] = field(default_factory=list)  # [{id, name, score}]
    findings: list[Finding] = field(default_factory=list)


def name_candidates(
    name: str, suppliers: list[Supplier]
) -> tuple[int, list[tuple[Supplier, float]]]:
    """Return (tier, hits). Tier 1/2 are exact; tier 3 is fuzzy; 0 = nothing."""
    norm = normalise_name(name)
    if not norm:
        return 0, []
    tier1 = [s for s in suppliers if normalise_name(s.name) == norm]
    if tier1:
        return 1, [(s, 100.0) for s in tier1]
    core = strip_legal_form(norm)
    tier2 = [s for s in suppliers if strip_legal_form(normalise_name(s.name)) == core and core]
    if tier2:
        return 2, [(s, 100.0) for s in tier2]
    scored = []
    for s in suppliers:
        other = strip_legal_form(normalise_name(s.name))
        score = max(fuzz.token_sort_ratio(core, other), fuzz.token_set_ratio(core, other) - 5)
        if score >= 80:
            scored.append((s, float(score)))
    scored.sort(key=lambda x: -x[1])
    return (3, scored[:5]) if scored else (0, [])


def match_supplier(name: str | None, vat: str | None, suppliers: list[Supplier]) -> SupplierMatch:
    name = (name or "").strip() or None
    vat = (vat or "").strip() or None
    if not name and not vat:
        return SupplierMatch(
            None,
            None,
            findings=[
                Finding(
                    "supplier_missing",
                    "blocking",
                    "The email doesn't say which supplier to order from.",
                    field="supplier",
                )
            ],
        )

    by_vat = None
    if vat:
        nv = normalise_vat(vat)
        by_vat = next((s for s in suppliers if s.vat_id and normalise_vat(s.vat_id) == nv), None)
    tier, hits = name_candidates(name, suppliers) if name else (0, [])
    exact = [s for s, _ in hits] if tier in (1, 2) else []
    cands = [{"id": s.id, "name": s.name, "score": round(sc)} for s, sc in hits]

    if by_vat is not None:
        if exact and by_vat.id not in {s.id for s in exact}:
            other = exact[0]
            return SupplierMatch(
                None,
                None,
                candidates=[{"id": by_vat.id, "name": by_vat.name, "score": 100, "via": "vat"}]
                + [{"id": s.id, "name": s.name, "score": 100, "via": "name"} for s in exact],
                findings=[
                    Finding(
                        "supplier_conflict",
                        "blocking",
                        f'The VAT ID {vat} belongs to {by_vat.name} ({by_vat.id}), but the name "{name}" '
                        f"is {other.name} ({other.id}). Decide which supplier this is.",
                        field="supplier",
                        details={"vat_supplier": by_vat.id, "name_supplier": other.id},
                    )
                ],
            )
        return SupplierMatch(by_vat.id, "vat", candidates=cands)

    if vat and len(exact) == 1 and exact[0].vat_id:
        s = exact[0]
        return SupplierMatch(
            None,
            None,
            candidates=[{"id": s.id, "name": s.name, "score": 100, "via": "name"}],
            findings=[
                Finding(
                    "supplier_conflict",
                    "blocking",
                    f'The name "{name}" matches {s.name} ({s.id}), but the document\'s VAT ID {vat} is '
                    f"not the one on file ({s.vat_id}).",
                    field="supplier",
                    details={"name_supplier": s.id},
                )
            ],
        )

    if len(exact) == 1:
        s = exact[0]
        why = "The document gives no VAT ID" if not vat else "The supplier has no VAT ID on file"
        return SupplierMatch(
            s.id,
            "name_exact",
            candidates=cands,
            findings=[
                Finding(
                    "supplier_name_only",
                    "warning",
                    f'Matched "{name}" to {s.name} ({s.id}) by name only. {why}; please confirm.',
                    field="supplier",
                )
            ],
        )

    if len(exact) > 1:
        return SupplierMatch(
            None,
            None,
            candidates=cands,
            findings=[
                Finding(
                    "supplier_ambiguous",
                    "blocking",
                    f'"{name}" matches several suppliers: '
                    + ", ".join(f"{s.name} ({s.id})" for s in exact)
                    + ". Pick the right one.",
                    field="supplier",
                )
            ],
        )

    if tier == 3:
        return SupplierMatch(
            None,
            None,
            candidates=cands,
            findings=[
                Finding(
                    "supplier_uncertain",
                    "blocking",
                    f'"{name}" is not an exact match for any supplier. Closest: '
                    + ", ".join(f"{c['name']} ({c['id']})" for c in cands[:3])
                    + ". Confirm one or create a new supplier.",
                    field="supplier",
                )
            ],
        )

    label = name or vat
    return SupplierMatch(
        None,
        None,
        findings=[
            Finding(
                "supplier_unknown",
                "blocking",
                f'"{label}" is not in the supplier master data. Create it (after checking it is '
                f"legitimate) or pick an existing supplier.",
                field="supplier",
                details={"name": name, "vat_id": vat},
            )
        ],
    )


def supplier_status_findings(supplier: Supplier) -> list[Finding]:
    if supplier.status == "blocked":
        return [
            Finding(
                "supplier_blocked",
                "blocking",
                f"{supplier.name} ({supplier.id}) is blocked. Nothing may be ordered from a blocked "
                f"supplier; reject the requisition or choose another supplier.",
                field="supplier",
            )
        ]
    if supplier.status != "active":
        return [
            Finding(
                "supplier_inactive",
                "blocking",
                f"{supplier.name} has status '{supplier.status}'.",
                field="supplier",
            )
        ]
    return []


# --------------------------------------------------------------------------- cost centers


def normalise_cc(code: str) -> str:
    m = re.fullmatch(r"\s*(?:cc|ks|kst)?[\s_.-]*(\d{4})\s*", code, re.IGNORECASE)
    return f"CC-{m.group(1)}" if m else code.strip().upper()


def cost_center_suggestions(
    text: str | None,
    requester: Employee | None,
    cost_centers: dict[str, CostCenter],
) -> list[dict]:
    """Hints for the clerk, never applied automatically."""
    out: list[dict] = []
    seen: set[str] = set()

    def add(code: str, reason: str) -> None:
        if code in cost_centers and code not in seen:
            seen.add(code)
            out.append({"code": code, "name": cost_centers[code].name, "reason": reason})

    if text:
        t = normalise_name(text)
        scored = sorted(
            ((fuzz.token_set_ratio(t, normalise_name(c.name)), c) for c in cost_centers.values()),
            key=lambda x: -x[0],
        )
        for score, c in scored[:2]:
            if score >= 70:
                add(c.code, f'Name resembles "{text}"')
    if requester is not None:
        if requester.default_cost_center:
            add(requester.default_cost_center, f"{requester.name}'s default cost center")
        for c in cost_centers.values():
            if c.owner_employee_id == requester.id:
                add(c.code, f"Owned by {requester.name}")
    return out


def match_cost_center(
    code: str | None, cost_centers: dict[str, CostCenter]
) -> tuple[str | None, list[Finding]]:
    if not code:
        return None, [
            Finding(
                "cost_center_missing",
                "blocking",
                "No cost center code is stated. It determines the cost center owner and the "
                "department head, so the chain can't be built without it.",
                field="cost_center",
            )
        ]
    norm = normalise_cc(code)
    if norm in cost_centers:
        return norm, []
    return None, [
        Finding(
            "cost_center_unknown",
            "blocking",
            f"Cost center {code} is not in the master data. Not falling back to a similar-looking code.",
            field="cost_center",
            details={"code": code},
        )
    ]
