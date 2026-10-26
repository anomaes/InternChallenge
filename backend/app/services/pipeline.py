"""The intake pipeline:

  .eml -> parse -> redact -> extract -> validate & ground -> [verify] -> match -> dedupe -> route

Every email becomes a requisition before anything can fail, so no email is ever lost:
if extraction fails the requisition lands in Needs review with an `extraction_failed`
issue and the clerk fills the form from the source. Logs carry IDs and timings only.
"""

import hashlib
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from sqlmodel import Session, delete, select

from app.db.models import Attachment, Email, LineItem, LLMRun, Redaction, Requisition
from app.db.session import engine
from app.domain.dates import suggest_delivery_date
from app.domain.duplicates import Candidate, find_duplicates
from app.domain.issues import Finding
from app.domain.master import MasterData
from app.domain.requester import resolve_requester
from app.domain.workflow import State
from app.ingest.eml import parse_eml
from app.ingest.source import build_source
from app.llm.checks import CHECK_VERSION, build_questions, run_checks
from app.llm.openai_extractor import OpenAIExtractor
from app.llm.provider import ExtractionError, Extractor
from app.llm.schema import Extraction
from app.llm.validate import drop_invalid, ground, parse_iso, semantic_errors
from app.privacy.redact import Redactor
from app.services.audit import log_event, transition
from app.services.bus import bus
from app.services.evaluate import add_findings, evaluate, lines_of
from app.services.routing import route
from app.services.settings_store import get_setting

log = logging.getLogger("pipeline")
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pipeline")

STAGES = ["parse", "redact", "extract", "verify", "match", "route"]


def D(value: float | None) -> Decimal | None:  # noqa: N802
    return None if value is None else Decimal(str(value))


# --------------------------------------------------------------------------- ingest


def ingest_email(
    session: Session, raw: bytes, source_name: str, actor: str = "system"
) -> Requisition:
    parsed = parse_eml(raw)
    email = Email(
        source_name=source_name,
        message_id=parsed.message_id,
        in_reply_to=parsed.in_reply_to,
        references=parsed.references,
        from_name=parsed.from_name,
        from_email=parsed.from_email,
        to=parsed.to,
        subject=parsed.subject,
        sent_at=parsed.sent_at_utc,
        sent_date_local=parsed.sent_date_local,
        body_text=parsed.body_text,
        body_was_html=parsed.body_was_html,
        thread=[m.as_dict() for m in parsed.thread],
        content_hash=parsed.content_hash,
        raw=raw,
        source_text=build_source(parsed),
    )
    session.add(email)
    session.flush()
    for att in parsed.attachments:
        session.add(
            Attachment(
                email_id=email.id,  # type: ignore[arg-type]
                filename=att.filename,
                content_type=att.content_type,
                size=len(att.data),
                sha256=att.sha256,
                page_count=att.page_count,
                text=att.text,
                data=att.data,
            )
        )
    req = Requisition(email_id=email.id, title=parsed.subject, idempotency_key=uuid.uuid4().hex)  # type: ignore[arg-type]
    session.add(req)
    session.flush()
    req.public_id = f"REQ-{req.id:04d}"
    session.add(req)
    log_event(session, req, actor, "received", f"Email received: {source_name}")
    session.commit()
    bus.publish("requisition", id=req.id, state=req.state, new=True)
    return req


def process_async(req_id: int) -> None:
    _executor.submit(_safe_process, req_id)


def _safe_process(req_id: int) -> None:
    try:
        process(req_id)
    except Exception:  # noqa: BLE001
        log.exception("pipeline failed for requisition %s", req_id)
        with Session(engine) as s:
            req = s.get(Requisition, req_id)
            if req is None:
                return
            req.stage = None
            add_findings(
                s,
                req,
                [
                    Finding(
                        "pipeline_error",
                        "blocking",
                        "Processing stopped on an internal error. Fill in the form from the source, or re-run processing.",
                    )
                ],
                "ingest",
            )
            if req.state in (State.INBOX, State.PROCESSING, State.EXTRACTED):
                if req.state == State.INBOX:
                    transition(s, req, State.PROCESSING, "system")
                transition(s, req, State.NEEDS_REVIEW, "system", "internal error")
            s.commit()
            bus.publish("requisition", id=req_id, state=req.state)


def _stage(session: Session, req: Requisition, stage: str | None) -> None:
    req.stage = stage
    session.add(req)
    session.commit()
    bus.publish("stage", id=req.id, stage=stage)


# --------------------------------------------------------------------------- process


def process(req_id: int, extractor: Extractor | None = None) -> None:
    started = time.monotonic()
    with Session(engine) as session:
        req = session.get(Requisition, req_id)
        if req is None:
            return
        email = session.get(Email, req.email_id)
        assert email is not None
        md = MasterData.load(session)
        transition(session, req, State.PROCESSING, "system")
        _stage(session, req, "parse")

        # -- redact ---------------------------------------------------------------
        _stage(session, req, "redact")
        redactor = Redactor()
        model_input = redactor.redact(email.source_text)
        session.exec(delete(Redaction).where(Redaction.email_id == email.id))  # type: ignore[arg-type]
        for kind, placeholder, original in redactor.items():
            session.add(
                Redaction(email_id=email.id, kind=kind, placeholder=placeholder, original=original)
            )  # type: ignore[arg-type]
        req.redaction_count = len(redactor.items())
        if req.redaction_count:
            log_event(
                session,
                req,
                "system",
                "redacted",
                f"{req.redaction_count} sensitive value(s) redacted before AI processing: "
                + ", ".join(sorted({k for k, _, _ in redactor.items()})),
            )

        # -- extract + validate + ground -----------------------------------------
        _stage(session, req, "extract")
        gl = sorted((g.code, g.name) for g in md.gl_accounts.values())
        if extractor is None:
            extractor = OpenAIExtractor(
                gl, use_cache=get_setting(session, "llm_cache_mode") == "cached"
            )
        extraction = _extract(session, req, extractor, model_input, set(md.gl_accounts))

        if extraction is not None:
            extraction.line_items = _meaningful_lines(extraction.line_items)
            grounding = ground(extraction, model_input)
            _apply_extraction(session, req, email, extraction, grounding)
            req.extraction_ok = True
            transition(session, req, State.EXTRACTED, "system")
        else:
            req.extraction_ok = False
        session.commit()

        # -- verify (decision checks, optional) -----------------------------------
        if extraction is not None and get_setting(session, "decision_checks_enabled"):
            _stage(session, req, "verify")
            evaluate(session, req, md)  # amounts first, so po_total can be checked
            run_decision_checks(session, req, model_input)
            session.commit()

        # -- match, requester, duplicates -----------------------------------------
        _stage(session, req, "match")
        rr = resolve_requester(email.thread, email.from_email, email.from_name, md)
        req.requester_id = rr.employee_id
        req.requester_source = rr.source
        if rr.employee_id:
            req.provenance = {
                **req.provenance,
                "requester": {
                    "status": "from_document",
                    "source": "thread" if rr.source == "thread" else "sender",
                    "reason": "Derived from the email thread"
                    if rr.source == "thread"
                    else "Sender of the email",
                },
            }
        add_findings(
            session, req, [fd for fd in rr.findings if fd.severity != "blocking"], "ingest"
        )
        evaluate(session, req, md)
        session.flush()
        _dedupe(session, req, email)
        session.commit()

        # -- route ---------------------------------------------------------------
        _stage(session, req, "route")
        if req.state == State.PROCESSING:
            transition(session, req, State.NEEDS_REVIEW, "system", "extraction failed")
            evaluate(session, req, md)
        else:
            route(session, req, "system", md)
        req.stage = None
        session.add(req)
        session.commit()
        bus.publish("requisition", id=req.id, state=req.state)
        log.info(
            "requisition %s processed in %.1fs -> %s", req.id, time.monotonic() - started, req.state
        )


def _extract(
    session: Session, req: Requisition, extractor: Extractor, source: str, gl_codes: set[str]
) -> Extraction | None:
    """One attempt, one retry with the validation errors fed back, then drop what still fails."""
    feedback: list[str] | None = None
    for attempt in (1, 2):
        run = LLMRun(
            requisition_id=req.id,
            kind="extract",
            model=extractor.model,
            prompt_version=extractor.prompt_version,
            attempt=attempt,
        )  # type: ignore[arg-type]
        try:
            call = extractor.extract(source, feedback)
        except ExtractionError as err:
            run.error = str(err)
            session.add(run)
            if attempt == 2 or "No OPENAI_API_KEY" in str(err):
                _extraction_failed(session, req, str(err))
                return None
            feedback = None
            continue
        run.model, run.cached, run.raw_output = call.model, call.cached, call.raw
        run.latency_ms, run.input_tokens, run.output_tokens = (
            call.latency_ms,
            call.input_tokens,
            call.output_tokens,
        )
        errors = semantic_errors(call.output, gl_codes)
        run.ok = not errors
        run.validation = {"errors": errors}
        session.add(run)
        if not errors:
            return call.output
        if attempt == 1:
            feedback = errors
            continue
        cleaned, dropped = drop_invalid(call.output, gl_codes)
        run.validation = {"errors": errors, "dropped": dropped}
        log_event(
            session,
            req,
            "system",
            "validation",
            f"Dropped invalid values after retry: {', '.join(dropped)}",
        )
        return cleaned
    return None


def _extraction_failed(session: Session, req: Requisition, error: str) -> None:
    add_findings(
        session,
        req,
        [
            Finding(
                "extraction_failed",
                "blocking",
                f"The AI extraction failed ({error}). The requisition was kept; fill in the form from "
                f"the source email, then acknowledge this issue, or re-run processing.",
            )
        ],
        "ingest",
    )
    log_event(session, req, "system", "extraction_failed", "Extraction failed; sent to review.")


def _apply_extraction(
    session: Session, req: Requisition, email: Email, x: Extraction, bad: dict[str, str]
) -> None:
    def p(key: str, *, evidence: str | None = None, source: str = "document") -> dict:
        entry: dict = {"status": "from_document", "source": source, "grounded": key not in bad}
        if key in bad:
            entry.update(status="unverified", reason=bad[key])
        if evidence:
            entry["evidence"] = evidence
        return entry

    prov: dict[str, dict] = {}
    req.title = x.summary or req.title
    req.message_kind = x.message_kind
    req.supplier_name_doc = x.supplier_name
    req.supplier_vat_doc = x.supplier_vat_id
    req.supplier_address_doc = x.supplier_address
    prov["supplier"] = p("supplier", evidence=x.supplier_name_quote)
    prov["supplier"]["grounded"] = "supplier" not in bad and "supplier_vat" not in bad
    if x.supplier_vat_id:
        prov["supplier_vat"] = p("supplier_vat", evidence=x.supplier_vat_id)

    req.cost_center_doc = x.cost_center_code
    req.cost_center_text = x.cost_center_text
    prov["cost_center"] = p("cost_center", evidence=x.cost_center_quote)

    req.currency = x.currency
    if x.currency:
        prov["currency"] = p("currency")

    # Delivery date: an absolute date found in the source is a fact; anything else is a suggestion.
    req.delivery_date_text = x.delivery_date_text
    iso = parse_iso(x.delivery_date_iso)
    req.delivery_date = None
    req.delivery_date_suggested = None
    if iso and "delivery_date" not in bad:
        req.delivery_date = iso
        prov["delivery_date"] = p("delivery_date", evidence=x.delivery_date_text)
    elif x.delivery_date_text:
        sug = suggest_delivery_date(x.delivery_date_text, email.sent_date_local)
        if sug:
            req.delivery_date_suggested = sug[0]
            prov["delivery_date"] = {
                "status": "suggested",
                "source": "computed",
                "reason": f'Suggested from "{x.delivery_date_text}": {sug[1]}.',
                "evidence": x.delivery_date_text,
            }

    req.quote_reference = x.quote_reference
    req.quote_date = parse_iso(x.quote_date_iso) if "quote_date" not in bad else None
    req.quote_valid_until = (
        parse_iso(x.quote_valid_until_iso) if "quote_valid_until" not in bad else None
    )
    if req.quote_valid_until:
        prov["quote_valid_until"] = p("quote_valid_until")

    req.vat_amount = D(x.vat_amount)
    req.vat_rate = D(x.vat_rate_percent)
    if x.vat_amount is not None:
        prov["vat_amount"] = p("vat_amount")
    req.stated_totals = [
        {
            "label": st.label,
            "amount": str(D(st.amount)),
            "includes_vat": st.includes_vat,
            "approximate": st.is_approximate,
            "source": st.source,
            "evidence": st.source_quote,
            "overridden": False,
        }
        for st in x.stated_totals
    ]
    for i, st in enumerate(x.stated_totals):
        if f"stated_totals.{i}" in bad:
            prov[f"stated_totals.{i}"] = p(f"stated_totals.{i}", evidence=st.source_quote)

    req.referenced_requests = [r for r in x.referenced_requests if "referenced_requests" not in bad]
    req.on_behalf_of_text = x.on_behalf_of
    req.prior_approval_claim = (
        (x.prior_approval_quote or "claims prior approval") if x.claims_prior_approval else None
    )
    req.gl_account = None
    req.gl_account_suggested = x.gl_account_suggestion
    req.gl_account_reason = x.gl_account_reason
    if x.gl_account_suggestion:
        prov["gl_account"] = {
            "status": "suggested",
            "source": "ai",
            "reason": x.gl_account_reason or "AI suggestion",
        }
    req.notes = list(x.notes_for_clerk[:4])
    req.provenance = prov

    session.exec(delete(LineItem).where(LineItem.requisition_id == req.id))  # type: ignore[arg-type]
    for i, ln in enumerate(x.line_items, start=1):
        lp: dict[str, dict] = {}
        for fld in (
            "quantity",
            "unit_price",
            "price_basis",
            "stated_line_total",
            "item_code",
            "source_quote",
        ):
            key = f"line.{i}.{fld}"
            if key in bad:
                lp[fld] = {
                    "status": "unverified",
                    "grounded": False,
                    "reason": bad[key],
                    "source": "document",
                }
        session.add(
            LineItem(
                requisition_id=req.id,  # type: ignore[arg-type]
                position=i,
                kind=ln.kind,
                description=ln.description.strip(),
                item_code=ln.item_code,
                quantity=D(ln.quantity),
                quantity_approximate=ln.quantity_is_approximate,
                unit=ln.unit,
                unit_price=D(ln.unit_price),
                price_basis=D(ln.price_basis) if ln.price_basis not in (None, 1) else None,
                stated_line_total=D(ln.stated_line_total),
                source_quote=ln.source_quote,
                provenance=lp,
            )
        )
    session.add(req)
    session.flush()


def _meaningful_lines(lines: list) -> list:
    """Drop empty echoes: a line with no quantity, price or total that repeats another line."""
    out = []
    for ln in lines:
        empty = ln.quantity is None and ln.unit_price is None and ln.stated_line_total is None
        dup = any(
            o.description.strip().casefold() == ln.description.strip().casefold() for o in out
        )
        if empty and dup:
            continue
        out.append(ln)
    return out


def run_decision_checks(session: Session, req: Requisition, model_input: str) -> None:
    lines = lines_of(session, req)
    questions = build_questions(
        {
            "currency": req.currency,
            "supplier_name_doc": req.supplier_name_doc,
            "supplier_vat_doc": req.supplier_vat_doc,
            "po_total": req.po_total,
            "vat_amount": req.vat_amount,
            "cost_center_doc": req.cost_center_doc,
            "delivery_date_doc": req.delivery_date.isoformat() if req.delivery_date else None,
        },
        [
            {
                "position": ln.position,
                "description": ln.description,
                "quantity": ln.quantity,
                "unit": ln.unit,
                "unit_price": ln.unit_price,
                "price_basis": ln.price_basis,
            }
            for ln in lines
        ],
    )
    if not questions:
        return
    run = LLMRun(
        requisition_id=req.id, kind="check", model="gpt-6-luna", prompt_version=CHECK_VERSION
    )  # type: ignore[arg-type]
    try:
        result = run_checks(
            model_input, questions, use_cache=get_setting(session, "llm_cache_mode") == "cached"
        )
    except Exception as err:  # noqa: BLE001  (the system is correct without this layer)
        run.error = f"{type(err).__name__}: {str(err)[:300]}"
        session.add(run)
        log_event(
            session,
            req,
            "system",
            "check_failed",
            "Decision checks unavailable; continuing without them.",
        )
        return
    run.model, run.cached, run.ok = result.model, result.cached, True
    run.latency_ms, run.input_tokens = result.latency_ms, result.input_tokens
    run.raw_output = str({q.field: result.probabilities.get(q.field) for q in questions})
    session.add(run)

    prov = dict(req.provenance)
    by_pos = {ln.position: ln for ln in lines}
    for fld, prob in result.probabilities.items():
        if prob is None:
            continue
        if fld.startswith("line."):
            _, pos, name = fld.split(".", 2)
            ln = by_pos.get(int(pos))
            if ln is not None:
                lp = dict(ln.provenance)
                lp[name] = {
                    **lp.get(name, {"status": "from_document", "source": "document"}),
                    "check": prob,
                }
                ln.provenance = lp
                session.add(ln)
        else:
            prov[fld] = {
                **prov.get(fld, {"status": "from_document", "source": "document"}),
                "check": prob,
            }
    req.provenance = prov
    session.add(req)
    log_event(
        session,
        req,
        "system",
        "checked",
        f"Decision checks: {len(questions)} values verified"
        + (" (cached)" if result.cached else ""),
    )


def _candidate(session: Session, r: Requisition, e: Email) -> Candidate:
    lines = lines_of(session, r)
    return Candidate(
        id=r.id,  # type: ignore[arg-type]
        public_id=r.public_id,
        state=r.state,
        requester_id=r.requester_id,
        supplier_id=r.supplier_id,
        cost_center_code=r.cost_center_code,
        po_total=r.po_total,
        sent_date=e.sent_date_local,
        content_hash=e.content_hash,
        body_key=hashlib.sha256(
            f"{e.from_email}|{' '.join(e.body_text.split()).casefold()}".encode()
        ).hexdigest(),
        message_id=e.message_id,
        lines_text=" ".join(
            f"{ln.item_code or ''} {ln.description}" for ln in lines if ln.kind == "item"
        ),
        title=r.title,
    )


def _dedupe(session: Session, req: Requisition, email: Email) -> None:
    others = [
        _candidate(session, r, e)
        for r, e in session.exec(
            select(Requisition, Email).where(
                Requisition.email_id == Email.id, Requisition.id < req.id
            )  # type: ignore[arg-type,operator]
        )
    ]
    res = find_duplicates(
        me=_candidate(session, req, email),
        message_kind=req.message_kind,
        referenced=req.referenced_requests,
        in_reply_to=[m for m in [email.in_reply_to, *email.references] if m],
        others=others,
    )
    if res.linked_to_id:
        req.linked_to_id, req.link_type, req.link_reason = (
            res.linked_to_id,
            res.link_type,
            res.link_reason,
        )
        session.add(req)
        log_event(
            session, req, "system", "linked", f"Linked to an earlier requisition: {res.link_reason}"
        )
    add_findings(session, req, res.findings, "ingest")


def reprocess(session: Session, req: Requisition, actor: str) -> None:
    """Run the whole pipeline again (e.g. after an extraction failure)."""
    from app.db.models import Issue

    for issue in session.exec(
        select(Issue).where(
            Issue.requisition_id == req.id, Issue.origin.in_(["ingest", "evaluate"])
        )
    ):  # type: ignore[attr-defined]
        session.delete(issue)
    req.linked_to_id = req.link_type = req.link_reason = None
    req.manual_approvers = {}
    if req.state != State.PROCESSING:
        from app.services.routing import supersede_run

        supersede_run(session, req)
        req.state = State.INBOX.value
        log_event(session, req, actor, "reprocess", "Processing restarted from the original email.")
    session.add(req)
    session.commit()
    process_async(req.id)  # type: ignore[arg-type]
