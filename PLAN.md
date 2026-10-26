# Plan: Purchase Requisition Automation

Working plan for the BLP take-home ([CHALLENGE_BRIEF.md](CHALLENGE_BRIEF.md)). Living document; decisions
taken so far are recorded in [Decisions log](#15-decisions-log).

---

## 1. Guiding principles

1. **The LLM reads, code decides.** The generative model only reports what the document *says*, with
   evidence. Matching, arithmetic, approval routing and state changes are deterministic, tested code.
2. **Never present a guess as a fact.** Every field carries a status (`confirmed`, `from_document`,
   `suggested`, `unverified`, `missing`, `conflict`) and a reason. Suggestions stay visibly suggestions
   until a human confirms them.
3. **Nothing is approved automatically.** Uncertainty routes to the clerk; a clean case goes straight
   to the first approver.
4. **Sensitive data never leaves the machine.** Card numbers, bank details and similar are redacted
   before any external API call, and logs carry IDs, not content.
5. **The UI is part of the product.** Polished, minimal, fast, and it explains *why* the system did
   what it did. Built around the clerk working the queue, with a focused view for approvers.

---

## 2. Stack

| Layer | Choice | Why |
| --- | --- | --- |
| Backend | **Python 3.12+, FastAPI** (JSON API) | Same language as the mock ERP, strong email/PDF libs, Pydantic schemas |
| DB | **SQLite + SQLModel** (SQLAlchemy) | Brief says SQLite is fine; models port to Postgres |
| Frontend | **React + Vite + TypeScript + Tailwind + shadcn/ui (Radix) + TanStack Query/Table + Motion** | Polished accessible primitives, dense tables, optimistic updates, smooth transitions |
| API types | OpenAPI → generated TS client (`openapi-typescript`) | End-to-end typesafety |
| Live updates | Server-Sent Events | Pipeline progress and new arrivals appear without refresh |
| Email | stdlib `email` (`policy.default`) | Plain text, HTML, attachments, encodings |
| PDF | `pypdf` (layout mode) for text; browser's native viewer for display | Quotes are text PDFs (verified), no OCR |
| LLM (generative) | **OpenAI API, structured outputs** (`responses.parse` + Pydantic), behind a small provider interface | One key covers extraction and checks |
| LLM (checks) | **OpenAI Decisions API** (`gpt-6-luna`), switchable at runtime, **off by default** | Calibrated probabilities to verify the extraction (§6) |
| Tests | `pytest`; Vitest for UI utils | |
| Run | one command (`make dev`) starts mock ERP, backend, frontend | Local only |

---

## 3. Repository layout

```
backend/
  app/
    main.py                 FastAPI app, routers, SSE
    api/                    requisitions, approvals, emails, attachments, master_data,
                            orders, workflow, settings, demo
    db/                     models.py, session.py, seed.py (master_data.json -> SQLite)
    ingest/                 eml.py (headers, body, HTML->text, thread split, attachments), pdf.py
    privacy/redact.py       sensitive-data redaction before external calls
    llm/
      provider.py           Extractor interface
      openai_extractor.py   generative extraction (structured outputs)
      checks.py             Decisions API verification
      prompts/              versioned prompt files
      schema.py             Pydantic extraction schema
    domain/                 reconcile.py, matching.py, requester.py, approval.py,
                            workflow.py, duplicates.py, issues.py
    notify/outbox.py        simulated notifications (no delivery)
    erp/client.py           mock PO API client (idempotency, 422 handling)
  tests/
frontend/                   Vite + React app
scripts/run_all.py          batch-run all 48 emails -> results table (cached LLM outputs)
README.md  PRODUCTION.md  PLAN.md  .env.example
```

Secrets: `OPENAI_API_KEY` in `.env` (gitignored). Only `.env.example` is committed. The repo will be
shared with BLP, so a key must never land in git history.

---

## 4. Pipeline

```
.eml ─► Parse ─► Redact ─► Extract ─► Validate & ground ─► [Verify] ─► Reconcile ─► Match ─► Dedupe ─► Route
        text,    cards,    LLM        schema, retry,       Decisions   numbers      master   link &   approval
        PDF,     IBAN,     struct.    evidence substring   API (opt.)  net/freight  data     flag     chain
        thread   AHV...    output
                                                                                         │
                                                         any blocking issue? ── yes ──► NEEDS_REVIEW
                                                                             └─ no ───► PENDING_APPROVAL
```

Each stage is a function `(requisition, master_data) -> (field updates, issues)`. An **issue** has
`code`, `severity` (`blocking` | `warning` | `info`), `field`, human message, and resolution state.
Every stage emits an SSE event (drives the live progress indicator in the UI).

---

## 5. Generative extraction (D3)

**Input:** labelled sections (redacted): email headers (From, Date, Subject), cleaned body with the
forwarded/quoted thread split into messages, each PDF's text.

**Output schema** (all fields nullable; the prompt says "null if not stated, never infer"):

- `message_kind`: new request / correction / repeat / approval reply / not a purchase request (e.g. the datasheet in `email_44`)
- `thread_messages[]`: author name + email, internal/external, role in the thread (requests / forwards / confirms / supplier offer). This is the input for the requester rule (§7)
- `supplier` (name, VAT ID, address text)
- `line_items[]`: description, item_code, quantity, unit, unit_price, **price_basis** (e.g. per 100), stated_line_total
- `stated_amounts`: net subtotal, discount, freight/surcharges, VAT amount + rate, gross total, currency
- `delivery_date_text` (raw) + `delivery_date_iso` (only if absolute)
- `cost_center_text`, `quote_valid_until`, `referenced_requests` (e.g. `PR-2026-0412`)
- `claims_prior_approval` + quote (e.g. `email_50`: "CFO hat mündlich zugestimmt"). Shown as a warning; the chain still runs in full
- `gl_account_suggestion`: one of the 12 GL codes given in the prompt, or null. Always shown as *suggested*; the clerk confirms
- `evidence`: exact source substring per key field

**Validation layers** (the answer to "what if the model returns garbage?"):

1. Structured outputs enforce the JSON schema at the API.
2. Pydantic validation: types, positive quantities, ISO currency, sane dates, GL code in master data.
3. **Grounding check**: every number / ID / evidence string must appear in the source after
   normalisation (`1'250.00` = `1.250,00` = `1,250.00`). Otherwise the field is `unverified`.
4. One retry with the validation errors fed back. If it still fails, an `extraction_failed` issue:
   the requisition exists, lands in Needs review, and the clerk fills the form from the source.
5. Refusal / truncation / timeout / API down: same path as 4. No email is ever lost.

Every run is stored in `extraction_runs` (model, prompt version, raw output, validation result,
latency, tokens). Model: the cheapest current OpenAI model that gets the 48 emails right, measured
with `scripts/run_all.py`.

---

## 6. Decision checks (Decisions API, switchable)

**What it is.** "System One" decision models (OpenAI Decisions API, TypeSafe Jev) don't generate
text. They answer typed questions with **calibrated probabilities**. OpenAI: `POST /v1/decisions`,
model `gpt-6-luna`, up to 400 questions per call, text / image / JSON input, $0.10 per 1M input
tokens, no output charge.

**Scope for now: checks only.** After extraction, every routing-relevant extracted value becomes a
`predicate` question against the (redacted) source text, all in one call:

- supplier name;
- supplier VAT ID;
- per line: quantity, unit, unit price;
- net total and currency;
- cost center;
- delivery date.

For example: *"The document states a unit price of 15.00 EUR per m for 'Cable carrier CK-40'."*

| Probability | Effect |
| --- | --- |
| ≥ high threshold | small "verified" chip on the field |
| between thresholds | warning, field marked `unverified` |
| < low threshold on a routing field (amount, supplier, cost center) | blocking issue → Needs review |

Why it's useful: the substring grounding check catches *invented* values, but not *misattributed* ones
(subtotal read as total, unit price from the wrong line). An independent model family is a real
second opinion.

**Switch.** Lives on the Settings & demo page, **off by default**, persisted in the `settings` table.

- **Off:** the stage is skipped and no chips are shown.
- **On:** new emails are checked. A "Re-run checks" action on the detail page covers existing cases.
- Thresholds are tuned on the 48 emails. The system is fully correct without this layer.

Later uses (not now): triage, GL suggestion, duplicate judgement, requester disambiguation.

---

## 7. Deterministic checks

**Amounts** (`reconcile.py`, `Decimal` everywhere)

- Line value = qty × unit_price ÷ price_basis.
- Cross-check line sums ↔ stated line totals ↔ stated net ↔ net + VAT ↔ gross. Any contradiction → blocking `amount_conflict` showing both figures (e.g. Kabelwerk: subtotal 4,380 vs total 4,830).
- No price → blocking `unpriced_line`.
- **Approval amount** = Σ line values **+ freight/surcharges**, excl. VAT, **discounts not subtracted** (decision 3; conservative: a discount never lowers the approval band). Converted to CHF via `fx_rates`; original currency and amount are kept.
- **PO total** = net after discount, excl. VAT. Freight and discount are sent as their own lines, so the ERP line sum matches the supplier's price. VAT goes in `tax_amount`.

**Requester** (`requester.py`, decision 4)

- The requester is the **original internal author** of the request: the earliest message in the thread written by a known employee. Forwarders and people who only confirm are not the requester; external senders (suppliers) never are.
  - `email_03`: the offer comes from the supplier, so the requester is Lukas Frei.
  - `email_45`: Sophie → Lukas → Anna → supplier, so the requester is Anna Widmer.
  - `email_46`: Andrea Roth proposed and Tobias confirmed, so the requester is Andrea Roth.
- When the requester comes from a thread rather than the sender, there is a visible "derived from thread" note. The clerk can change it. That matters because it drives the self-approval rule.
- Unknown requester (not in `employees`) → blocking.

**Supplier**

- VAT ID match (normalised) → `confirmed`.
- Name-only match (fuzzy) → warning, clerk confirms. There are look-alikes: Acme/ACME, Müller/Mueller.
- No match → blocking, with a "create supplier" action.
- `blocked` → blocking, no override.
- VAT and name point to different suppliers → blocking `supplier_conflict`.

**Cost center**

- Exact code match only; otherwise blocking.
- Hints such as the requester's `default_cost_center`, or a signature contradicting the stated code (`email_48`), are suggestions or warnings only.

**Delivery date**

- Relative phrases ("Ende Monat") → a *suggested* date computed from the email date.
- Missing does **not** block approval; it **blocks ordering** (the normal case per the brief).

**Quote validity**: expired quote → warning.

**Duplicates / corrections**

- Signals: `In-Reply-To`/`References`, explicit request IDs, `message_kind`, and a fingerprint (requester, supplier, items, amount, time window).
- On a match: link + flag. The clerk chooses *duplicate*, *apply as correction*, or *keep both*.
- A corrected rejected request restarts its chain from step 1.

---

## 8. Approval chain (`approval.py`, most heavily tested)

1. **Band:** the first band whose upper bound ≥ approval amount in CHF. Upper bounds inclusive (decision 1), so CHF 1,000.50 → band 2.
2. **Resolve roles → persons:**
   - cost center owner;
   - department head (via the cost center's department);
   - finance / CFO / CEO: the holder without `deputy_for`.
3. **Collapse** consecutive steps held by the same person into one step covering both roles.
4. **Self-approval:**
   - A step whose person is the requester is reassigned to the next step's person who is not the requester. It is marked "on behalf of <role>, requester can't approve".
   - **No re-collapse afterwards** (decision 2): if that person also holds the following step, they approve twice.
   - If no such person exists → blocking `needs_manual_approver`; the clerk assigns one.
5. **Snapshot:** the chain is persisted with a run number. Editing amount, supplier, cost center or requester during approval rebuilds and restarts the chain, logged.

Test fixtures from the real emails:

| Email | Case | Expected chain |
| --- | --- | --- |
| `email_12` | CHF 999 | Sara Keller |
| `email_46` | CHF 2,600. Requester Andrea Roth owns CC-1004 *and* heads OPS | collapsed to one step → it's hers → nobody else in band 2 → `needs_manual_approver` |
| `email_50` | CHF 62k, requester Tobias, "CFO already approved" | Andrea (collapsed) → Daniela → Roger, bypass claim flagged |
| `email_03` | requester Lukas owns CC-2001, band 3 | Markus (on behalf of owner) → Markus → Daniela |
| `email_45` | EUR 41,200 ≈ CHF 39,552, requester Anna, CC-2001 | Lukas → Markus → Daniela |
| synthetic | CHF 1,000.50 | band 2 |
| synthetic | CEO requests > 250k | `needs_manual_approver` |

---

## 9. Workflow states

```
INBOX → PROCESSING → EXTRACTED → NEEDS_REVIEW → PENDING_APPROVAL → APPROVED → ORDERED
                                     │                 │
                                     └──► CLOSED_DUPLICATE   └──► REJECTED (reason kept)
```

- `PROCESSING` has visible sub-stages (parse → redact → extract → verify → match → route).
- Transitions live in one table, enforced server-side; every transition and every field edit goes to the `events` audit log.
- When a step becomes active, a notification is written to the **outbox** (recipient, subject, link to the approver view). Delivery by email is future work.

---

## 10. Privacy

- **Redaction before any external call** (`privacy/redact.py`). Each match is validated, not just pattern-matched:
  - payment card numbers: Luhn check;
  - IBANs: mod-97 check;
  - Swiss AHV numbers (`756.xxxx.xxxx.xx`): checksum;
  - credentials (`password:`, API-key shapes).
- Matches are replaced by typed placeholders (`[CARD_1]`). The mapping stays in the local DB, and the UI shows a "2 values redacted before AI processing" badge.
- The 48 sample emails contain none of these (verified), so a **synthetic test email** with a card number and an IBAN demonstrates it.
- **Data minimisation:** only From/Date/Subject, body and attachment text go to the LLM.
- **Logs:** requisition IDs and stage timings only, never content.
- **Production** (PRODUCTION.md): zero data retention / EU region, DPA, retention policy, optional pseudonymisation of names.

---

## 11. Database

**Master data** (seeded from `master_data.json` by `seed.py`, never read at request time):
`suppliers`, `cost_centers`, `departments`, `employees`, `gl_accounts`, `approval_bands`, `fx_rates`.

**Requisition data:**

| Table | Holds |
| --- | --- |
| `emails` | raw .eml, message-id, references, sender, date, parsed text, attachments |
| `requisitions` | state, header fields, approval amount, PO total, VAT, currency, `amount_chf`, `linked_to_id`, `link_type` |
| `line_items` | per-line fields + stated line total, line kind (item / freight / discount) |
| `field_provenance` | per field: source, evidence span, status, check probability |
| `issues` | code, severity, message, resolved by/at |
| `approval_steps` | run number, order, roles covered, approver, on-behalf-of, status, decided at, comment |
| `extraction_runs` / `check_runs` | model, prompt version, raw I/O, validation result, latency, tokens |
| `redactions` | type, placeholder, original (local only) |
| `notifications` | simulated outbox |
| `events` | audit log |
| `purchase_orders` | ERP response, PO number, warnings |
| `settings` | runtime switches (decision checks on/off, thresholds, LLM cache mode) |

---

## 12. UI / UX (major focus)

**Direction:** minimal, "Apple-style", **light theme only**, English only.

- **Visual:** generous whitespace, neutral greys plus a single accent; state colours used sparingly and consistently.
- **Typography:** system font stack (SF Pro on Mac) / Inter, tabular figures for amounts.
- **Surfaces:** soft depth (hairline borders, subtle shadows, translucent sticky header).
- **Motion:** short and purposeful; respects `prefers-reduced-motion`.
- **Snappy:**
  - optimistic updates;
  - skeletons instead of spinners;
  - keyboard-first: `⌘K` palette, `J/K` to move, `Enter` to open, `A`/`R` approve/reject;
  - toasts with undo where reversible.
- **Design tooling:** build a small design system first (tokens, type scale, components) with the `frontend-design` / `ui-ux-pro-max` skills (or the *impeccable* plugin if installed).

### Clerk screens

1. **Home: Needs your attention**
   - Summary strip (counts): Needs review · Waiting for approvers · Ready to order · Order failed.
   - Attention list grouped by reason, each row one click from its fix:
     - blocked or unknown supplier;
     - amount conflict;
     - missing or unknown cost center;
     - suspected duplicate / correction;
     - manual approver needed;
     - approved but missing delivery date;
     - order failed.
   - Live "just arrived" feed.
2. **Requisitions table:** dense but airy (~40px rows).
   - Columns: ID, received, requester, supplier (with match badge), amount (original + CHF), **state with mini pipeline indicator**, current step ("2/3 · Daniela Huber"), issues.
   - Filter chips, search, sort, saved views, keyboard navigation. Click → detail.
3. **Requisition detail:**
   - **Header:** a state stepper showing where the case is, plus the approval chain timeline with on-behalf-of markers.
   - **Main:** the extracted form with a status badge per field, and a "why" popover (evidence, grounding, check probability).
   - **Issues:** issue cards with one-click resolutions (confirm supplier, pick cost center, set delivery date, assign approver, resolve duplicate).
   - **Source panel:** email text with evidence highlighting.
   - **"View PDF"** opens a resizable **side panel** with the browser's native PDF viewer (served by the backend). Simple to build; evidence highlighting stays in the text view.
   - Activity log (events, redactions, extraction runs).
   - Action bar: send to approval / reject / place order.
4. **Workflow overview (D2):** state diagram with live counts per state; click a state to filter the table.
5. **Purchase orders:** ERP results with PO number and warnings.
6. **Master data:** read-only browser; create a supplier from an unknown-supplier issue.

### Approver view

The flow it simulates: the approver gets an email (future work; shown in the outbox) with a link to the case.

- **Fixed paths**, so a demo tab can stay open: `/approver/EMP-701` is that approver's queue; `/approver/EMP-701/r/<id>` is one decision.
- **Decision page:** one focused column, everything needed at a glance:
  - what (items summary), how much (net, CHF, VAT);
  - supplier and its status, cost center and its owner, requester;
  - why you're asked (role, step x of y, previous approvals);
  - clerk notes and resolved issues;
  - "View PDF" side panel.
- **Actions:** Approve / Reject (reason required), keyboard `A`/`R`.
- Guards: a requester can't approve their own requisition; steps can't be taken out of order.

### Settings & demo page (`/demo`)

- **Inbox simulator:**
  - the 48 sample emails with a "deliver" button each, "deliver next", and "deliver all" with an interval (watch them flow through);
  - drag-and-drop upload of an unseen `.eml` for the interview.
- **Switches:**
  - **Decision checks** (off by default);
  - LLM cache mode (use cached extraction for known emails / always live; unseen emails are always live).
- **Outbox:** simulated notifications with links that open the approver view in a new tab.
- **Quick links:** approver views for every approver.
- **System status:** mock ERP health, API key configured, DB counts.
- **Reset:** wipe requisitions and reseed master data (with confirm).

---

## 13. ERP submission

- Only from `APPROVED`, and only once the delivery date and required fields are present.
- `Idempotency-Key` = requisition id. `tax_amount` is sent.
- **201:** store PO number + warnings → `ORDERED`.
- **422:** show problems, stay `APPROVED` with an `order_failed` issue.
- **Connection error:** retry with backoff, surfaced in the UI.

---

## 14. Build phases

| # | Phase | Outcome |
| --- | --- | --- |
| 0 | Repo hygiene: `.gitignore`, `.env.example`, Makefile, backend + frontend skeletons | `make dev` runs three services |
| 1 | DB models, seed, email/PDF parsing, thread splitting, redaction + tests | Parsed, redacted text of all 48 emails |
| 2 | **Rules core**: reconcile, matching, requester, approval chain, state machine + tests | Deterministic logic done before any LLM |
| 3 | Generative extraction + validation + grounding + cache, `run_all.py` | Sensible results table for 48 emails |
| 4 | Decision checks behind the switch + threshold tuning | Probabilities in the results table |
| 5a | Design system (tokens, components) | Consistent look |
| 5b | Clerk UI: home, table, detail, PDF panel, workflow overview | Clerk flow end to end |
| 5c | Approver view + outbox | Approval flow end to end |
| 5d | Settings & demo page, SSE live updates | Demo-ready |
| 6 | Duplicates/corrections, ERP submission | All flows |
| 7 | README, PRODUCTION.md, rehearsal with unseen emails, video | Submission |

---

## 15. Decisions log

| # | Topic | Decision |
| --- | --- | --- |
| 1 | Band boundaries | Upper bound inclusive (CHF 1,000.50 → band 2) |
| 2 | Collapsing after self-approval pass-on | No re-collapse: the substitute approves at each step they hold |
| 3 | Amount for the band | Freight counts; discounts are not subtracted |
| 4 | Requester in forwards | Original internal author, not the forwarder |
| 5 | Third-party LLM | OpenAI acceptable, with redaction of sensitive data first |
| 6 | LLM provider | OpenAI for extraction and decision checks (single key) |
| 7 | Decisions API scope | Verification checks only, runtime switch, off by default |
| 8 | UI | Clerk-centric; separate approver view on fixed paths; light theme only; English only |
| 9 | Hosting | Local only |
| 10 | Budget | A few dollars of API spend; LLM outputs cached during development |

## 16. Future work (goes into README / PRODUCTION.md)

- Email notifications to approvers (outbox already models them), real auth, deputies and holiday cover.
- Decisions API for triage, GL suggestion, duplicate judgement.
- Pseudonymising personal names before LLM calls.
- Live mailbox integration, queue workers and Batch API for 10× volume, daily ECB FX feed, extraction accuracy monitoring.
