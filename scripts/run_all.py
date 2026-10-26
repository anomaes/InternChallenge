"""Run every sample email through the real pipeline and print a results table.

    backend/.venv/bin/python scripts/run_all.py                 # uses cached model output
    EXTRACTION_MODEL=gpt-5.4-nano backend/.venv/bin/python scripts/run_all.py --live
    backend/.venv/bin/python scripts/run_all.py --checks        # include decision checks

Uses a throwaway database, so the app's data is untouched. Model calls are made in
parallel first (filling the response cache), then the pipeline runs sequentially in
the order a mailbox would deliver the emails, so duplicate detection is deterministic.
"""

import argparse
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
_tmp = Path(tempfile.mkdtemp(prefix="run-all-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'run_all.db'}"

from email import policy  # noqa: E402
from email.parser import BytesParser  # noqa: E402

from sqlmodel import Session, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.models import ApprovalStep, Email, Issue, LineItem, Requisition  # noqa: E402
from app.db.seed import seed_master_data  # noqa: E402
from app.db.session import create_tables, engine  # noqa: E402
from app.domain.master import MasterData  # noqa: E402
from app.domain.reconcile import fmt  # noqa: E402
from app.ingest.eml import parse_eml  # noqa: E402
from app.ingest.source import build_source  # noqa: E402
from app.llm.openai_extractor import OpenAIExtractor  # noqa: E402
from app.llm.provider import ExtractionError  # noqa: E402
from app.privacy.redact import Redactor  # noqa: E402
from app.services.pipeline import ingest_email, process  # noqa: E402
from app.services.settings_store import set_setting  # noqa: E402


def mailbox_order(paths: list[Path]) -> list[Path]:
    def sent(p: Path) -> float:
        msg = BytesParser(policy=policy.default).parsebytes(p.read_bytes())
        try:
            return msg["Date"].datetime.timestamp()  # type: ignore[union-attr]
        except (AttributeError, TypeError, ValueError):
            return 0.0

    return sorted(paths, key=lambda p: (sent(p), p.name))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="ignore cached model output")
    ap.add_argument("--checks", action="store_true", help="run the decision checks too")
    ap.add_argument("--only", nargs="*", help="email file names to run")
    ap.add_argument("--out", default=str(ROOT / "scripts" / "results.md"))
    ap.add_argument("--prune", action="store_true", help="delete cache entries this run didn't use")
    args = ap.parse_args()

    create_tables()
    with Session(engine) as s:
        seed_master_data(s, force=True)
        set_setting(s, "llm_cache_mode", "live" if args.live else "cached")
        set_setting(s, "decision_checks_enabled", args.checks)
        s.commit()
        md = MasterData.load(s)

    paths = mailbox_order(sorted(settings.sample_emails_dir.glob("*.eml")))
    if args.only:
        paths = [p for p in paths if p.name in args.only]

    # 1. Model calls in parallel (cache warm-up), identical input to what the pipeline sends.
    gl = sorted((g.code, g.name) for g in md.gl_accounts.values())
    extractor = OpenAIExtractor(gl, use_cache=not args.live)
    started = time.monotonic()

    def warm(p: Path) -> tuple[str, str | None]:
        try:
            extractor.extract(Redactor().redact(build_source(parse_eml(p.read_bytes()))))
            return p.name, None
        except ExtractionError as err:
            return p.name, str(err)

    with ThreadPoolExecutor(max_workers=8) as pool:
        for name, err in pool.map(warm, paths):
            if err:
                print(f"  ! {name}: {err}", file=sys.stderr)
    print(
        f"model calls done in {time.monotonic() - started:.0f}s ({settings.extraction_model})",
        file=sys.stderr,
    )

    # 2. The real pipeline, sequentially, from the cache.
    cached = OpenAIExtractor(gl, use_cache=True)
    with Session(engine) as s:
        set_setting(s, "llm_cache_mode", "cached")
        s.commit()
    for p in paths:
        with Session(engine) as s:
            req = ingest_email(s, p.read_bytes(), p.name)
            rid = req.id
        process(rid, extractor=cached)  # type: ignore[arg-type]

    rows = []
    with Session(engine) as s:
        for req, email in s.exec(
            select(Requisition, Email)
            .where(Requisition.email_id == Email.id)
            .order_by(Requisition.id)
        ):  # type: ignore[arg-type]
            steps = s.exec(
                select(ApprovalStep)
                .where(ApprovalStep.requisition_id == req.id, ApprovalStep.run == req.approval_run)
                .order_by(ApprovalStep.position)
            ).all()
            issues = s.exec(
                select(Issue).where(Issue.requisition_id == req.id, Issue.status == "open")
            ).all()
            blocking = sorted({i.code for i in issues if i.severity == "blocking"})
            warnings = sorted({i.code for i in issues if i.severity == "warning"})
            probs = [
                (k, v.get("check")) for k, v in req.provenance.items() if v.get("check") is not None
            ]
            for ln in s.exec(select(LineItem).where(LineItem.requisition_id == req.id)):
                probs += [
                    (f"line.{ln.position}.{k}", v.get("check"))
                    for k, v in ln.provenance.items()
                    if v.get("check") is not None
                ]
            lowest = min(probs, key=lambda kv: kv[1]) if probs else None
            chain = " → ".join(
                md.name(st.approver_id).split()[0] if st.approver_id else "?" for st in steps
            )
            rows.append(
                [
                    email.source_name.replace(".eml", ""),
                    req.state.replace("_", " ").lower(),
                    md.name(req.requester_id) if req.requester_id else "—",
                    req.supplier_id or "—",
                    req.cost_center_code or "—",
                    f"{req.currency or ''} {fmt(req.po_total)}".strip(),
                    fmt(req.approval_amount_chf),
                    str(req.band_position or "—"),
                    chain or "—",
                    ", ".join(blocking) or "—",
                    ", ".join(warnings) or "—",
                ]
                + ([f"{lowest[0]} {lowest[1]:.2f}" if lowest else "—"] if args.checks else [])
            )

    header = [
        "email",
        "state",
        "requester",
        "supplier",
        "cc",
        "net",
        "CHF (approval)",
        "band",
        "chain",
        "blocking",
        "warnings",
    ]
    if args.checks:
        header.append("lowest check")
    lines = [
        f"# Results: all sample emails ({settings.extraction_model})",
        "",
        "Generated by `scripts/run_all.py`. State after the pipeline, before any human action.",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "---|" * len(header),
    ]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    text = "\n".join(lines) + "\n"
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)

    if args.prune and not args.only:
        from app.llm.cache import USED

        stale = [f for f in settings.llm_cache_dir.glob("*.json") if f.stem not in USED]
        for f in stale:
            f.unlink()
        print(f"pruned {len(stale)} unused cache entries, kept {len(USED)}", file=sys.stderr)


if __name__ == "__main__":
    main()
