# Purchase Requisition Automation

Turns purchase-request emails into checked, routed, approvable requisitions, and books
them in the ERP once fully approved. Built for the BLP take-home ([brief](CHALLENGE_BRIEF.md)).

The one rule everything is built around: **the LLM reads, code decides.** The model only
reports what an email says, with evidence. Matching, arithmetic, approval routing and
state changes are deterministic, tested code. Anything the system can't establish waits
for a human, visibly; nothing is approved automatically.

## Run it

Requires Python 3.12+ and Node 22+.

```bash
make setup   # venv + dependencies; creates .env from .env.example
make dev     # mock ERP :8080, backend :8000, app http://localhost:5173
make test    # 72 backend tests + frontend tests, offline
```

Put an `OPENAI_API_KEY` in `.env` for live extraction. **Without a key the app still runs
on all 48 sample emails**: model responses for them are committed in `backend/llm_cache/`,
keyed by a hash of the redacted input. An unseen email always goes to the model.

Then open **Inbox simulator** and press *Deliver all* to watch the samples arrive, or drop
any `.eml` onto the page. `demo/synthetic_sensitive_data.eml` shows redaction.

## A tour

| Screen | What it's for |
| --- | --- |
| **Needs attention** | The clerk's home: counts, and everything waiting for a human grouped by reason (supplier problems, amounts to decide, duplicates, approver needed, order data missing) |
| **Requisitions** | All cases; filter by state, search, sort, `J`/`K`/`Enter`, `⌘K` anywhere |
| **Requisition** | The route (arrival, review, each approver as a station, order), issues with one-click fixes, every field with its status and a "why" popover, the source email with evidence highlighted, the PDF side by side, the AI's raw output and the audit log |
| **Workflow** (D2) | The state diagram with live counts |
| **Approver view** | `/approver/EMP-701` is Daniela Huber's queue; `/approver/EMP-701/r/<id>` one focused decision; `A` approves, `R` rejects (reason required) |
| **Inbox simulator** | Deliver samples, upload unseen emails, the outbox, switches, system status, reset |

## How it works

```
.eml ─► parse ─► redact ─► extract ─► validate & ground ─► [verify] ─► reconcile ─► match ─► dedupe ─► route
```

- **Parse** (`ingest/`): stdlib `email`; HTML bodies to text; PDF text with `pypdf` in
  layout mode (the quotes are digital, no OCR). Forwarded and quoted messages are split
  into a thread deterministically, so the requester rule doesn't depend on the model.
- **Redact** (`privacy/redact.py`): card numbers (Luhn), IBANs (mod-97), AHV numbers
  (checksum) and credentials become `[CARD_1]`-style placeholders before any external call.
  Validation matters: the samples contain VAT IDs and quote numbers that naive patterns
  would destroy. None of the 48 trigger a redaction.
- **Extract** (`llm/`): one OpenAI call with structured outputs; details below.
- **Reconcile, match, route** (`domain/`): pure functions over a master-data snapshot.
- **Dedupe**: explicit request IDs, `In-Reply-To`, identical content, same sender and
  text (a resend), or same requester, supplier and items/amount within 30 days.
- Every email becomes a requisition *before* anything can fail. If extraction fails it
  lands in Needs review with the reason, and the clerk fills the form from the source.

Stack: FastAPI, SQLModel on SQLite, React + Vite + TypeScript + Tailwind with Radix
primitives, TanStack Query, server-sent events for live updates. The frontend's API types
are generated from the backend's OpenAPI schema (`make gen-api`).

## The LLM part (D3)

**Prompt**: [`backend/app/llm/prompts/extract_v2.md`](backend/app/llm/prompts/extract_v2.md)
(v1 kept for comparison). It asks for what is *written*: null if not stated, never infer,
never compute, verbatim evidence quotes.

**Schema**: [`backend/app/llm/schema.py`](backend/app/llm/schema.py). Every field is required
but nullable, so the model must say null rather than leave a field out. Line items carry
a `kind` (item, freight, surcharge, discount), a `price_basis` ("21.00 / 100"), the printed
line total and an "approximate" flag. Every printed total is reported separately, never
merged into one.

**What happens when the model returns garbage**, layer by layer:

1. Structured outputs enforce the JSON schema at the API.
2. Pydantic validates types.
3. Semantic checks: positive quantities, ISO currency, real dates, GL code in master data.
   Errors go back to the model once; whatever is still wrong after the retry is set to
   null, so it surfaces as a missing value instead of a wrong one.
4. **Grounding**: every number, ID and quote must be found in the source after
   normalising number formats (`1'250.00` = `1.250,00` = `1,250.00`). A value that can't be
   found is marked *unverified*; on a routing field that blocks.
5. **Reconciliation**: quantity × price must equal the printed line total, and the lines
   must add up to every printed total (plus VAT where the label says so). A contradiction
   blocks routing and shows both figures.
6. API errors, refusals, truncation and timeouts take the `extraction_failed` path.

Layers 4 and 5 earned their keep during development. One prompt version turned
"21.00 / 100" into 0.21 per 100, and another listed the same office chairs twice. Both
were caught (an unverified value; a total that contradicts the lines) and sent to review
instead of being routed; then the prompt was fixed. `tests/test_pipeline.py` also feeds
the pipeline a broken model and a garbage-producing one.

**Model choice**: `gpt-6-luna` at medium reasoning effort, picked with
`scripts/run_all.py` by running all 48 emails through nine models and comparing every
outcome with hand-checked results:

| Model | Routed wrongly | Clean cases held for review by mistake |
| --- | --- | --- |
| **gpt-6-luna** | 0 | 0 |
| gpt-5.5, gpt-6.1-sol, gpt-6-astra | 0 | 0 (minor differences in the reason given) |
| gpt-5.6-luna, gpt-5.6-sol, gpt-5.6-terra | 0 | 1 |
| gpt-6-sol | 0 | 2 |
| gpt-5.4-mini | 0 | 0 at medium effort; at low effort it duplicated a line on email_12 in one of three runs |

No model routed anything wrongly; the validation layers above turned every misreading
into a review case. `gpt-6-luna` matched the hand-checked results most closely and is
among the cheapest. Its one difference is arguably an improvement: it reads email_04's
"bitte das übliche, gleicher Lieferant wie immer" as a repeat of an earlier order. The
48 emails took about 162k input and 51k output tokens, about 12 s per email. Caveat:
this is one full run per model; the repeat runs that would show run-to-run stability
were cut short when the API credits ran out.

**Decision checks** (a switch on the simulator page, off by default): after extraction the
OpenAI Decisions API (`gpt-6-luna`) rates predicates such as *"The document lists 'Cable
carrier CK-40' with quantity 200 m at a unit price of 15.00 EUR"* with a calibrated
probability. Grounding catches invented values; this catches misattributed ones. The
phrasing mattered: separate quantity and price questions gave confident false negatives
on lump-sum lines, while one predicate per line scored 1.00 on every correct line and
0.00 on planted errors. Thresholds: verified at 0.80 and above, routing blocked below
0.50. Every correct value in the samples scored at least 0.86; Kabelwerk's
self-contradicting total scored 0.17. (The thresholds were tuned on `gpt-5.4-mini`'s
extractions.) One trade-off: the Decisions API only accepts `gpt-6-luna`, the same model
that now extracts, so the check is no longer a different model family. It is still a
different kind of question (rate a stated claim, not generate), but less independent
than before.

## Results on the 48 sample emails

Full table: [`scripts/results.md`](scripts/results.md) (`make results` regenerates it).
**31 go straight to their first approver; 17 wait for the clerk, each for a reason a
human should decide:**

| Email | Why it waits |
| --- | --- |
| 01 | Says "as in the attached quote", but nothing is attached (despite the file name) |
| 29 | The resend of 01 with the PDF: linked as a duplicate; "apply as correction" fixes 01 |
| 02, 27, 44 | No prices (44's attachment is a datasheet, not a quote); 02 names its cost center only as "the London office" (suggested, not applied) |
| 04 | "Bitte das übliche": nothing to go on; flagged as a repeat of an unidentified earlier order |
| 08 | Supplier Stahlhandel Wyss AG is not in the master data (the clerk can create it) |
| 09 | Baltic Steel is blocked |
| 11 | The name says Mueller Industriebedarf AG, the VAT ID says Müller Industriebedarf |
| 24 | Kabelwerk quote: subtotal 4,380 but total 4,830 |
| 28 | "Roughly ten" sensors for "around five thousand euros" |
| 30 | A correction that doesn't say which request it corrects |
| 34 | The SDS binder line has no price (the email says it's free; a human confirms) |
| 39 | Refers to PR-2026-0412, which isn't in this system |
| 40 | Cost center CC-9100 doesn't exist |
| 23, 46 | The requester, Andrea Roth, owns the cost center and heads the department; the chain offers nobody else |

The chains for the cases in the plan come out as specified. email_03: Markus Schmid (on
behalf of Lukas Frei, the requester), then Markus Schmid again, then Daniela Huber.
email_45: requester Anna Widmer, from the bottom of a three-times forwarded thread.
email_50: the full chain up to the CFO despite "Roger Studer (CFO) hat mündlich
zugestimmt", which is flagged to every approver.

## Assumptions and decisions

Where the brief left room, I decided as follows (also in [PLAN.md](PLAN.md#15-decisions-log)):

- **Band upper bounds are inclusive**: CHF 1,000.00 is band 1, CHF 1,000.50 band 2.
- **The approval amount counts freight and surcharges and doesn't subtract discounts**,
  so a conditional volume discount can't lower the band. The PO total is net after
  discount. VAT is recorded and sent as `tax_amount`, never routed on.
- **No re-collapse after a self-approval pass-on**: if the substitute also holds the next
  step, they approve twice (email_21: Andrea Roth approves on behalf of Hans Meier, then
  as department head). Merging them would also be a reading of the brief; I chose the
  stricter one.
- **The requester is the original internal author** of the thread, not the forwarder.
  It's shown as "derived from thread" and the clerk can change it.
- **Suppliers**: VAT ID first. An exact name match without a VAT ID routes, with a visible
  warning; anything fuzzy or ambiguous blocks and offers candidates. A name and a VAT ID
  that point to different suppliers always block.
- **Cost centers**: exact code only. `CC 1002` is `CC-1002` written differently; `CC-9100`
  is unknown.
- **Delivery dates**: an absolute date found in the text is used. Relative phrases
  ("Ende Monat", "week 24") give a *suggested* date, computed from the email date, that
  the clerk confirms. A missing date doesn't block approval, only the order.
- **Ordering**: after the last approval the order is booked automatically if everything
  the ERP requires is present; otherwise it waits under "Approved, details missing". The
  idempotency key is a UUID per requisition rather than its ID, because the ERP keeps its
  orders across a reset of this app while the IDs start again.
- **GL accounts** are suggested by the model, shown as suggestions, and sent to the ERP
  only once the clerk confirms one.
- **Suppliers created by the clerk** from an unknown-supplier issue are allowed (prefilled
  from the document, never automatic), as the brief offers.
- **Corrections**: "apply as correction" copies what the correction states onto the
  original and restarts its chain from step 1; the correction is closed and linked.

## What I left out

As the brief asks: real authentication (the approver ID in the URL stands in for a login;
the server still enforces turn order and the self-approval rule), email delivery
(notifications go to a visible outbox), deputies and holiday cover, OCR, Word and Excel,
multi-tenancy, and a real ERP. Exchange rates are the fixed table; in production they
would come from a daily ECB feed. More in [PRODUCTION.md](PRODUCTION.md).

## With another week

1. **An accuracy harness**: hand-labelled expected values for the 48 emails, scored per
   field on every prompt or model change, instead of reading `scripts/results.md`.
2. **Queue workers** (the pipeline out of the web process), Postgres, and the Batch API
   for volume; PRODUCTION.md has the 10× plan.
3. **Email in and out**: a mailbox poller instead of the simulator, and approval emails
   with signed one-click links.
4. **Learning from the clerk**: every correction is already in the audit log. Use it to
   tune prompts, spot suppliers and templates that often need fixing, and suggest
   supplier aliases.
5. **The Decisions API beyond checks**: triage, GL suggestions and duplicate judgement.

## Deviations from PLAN.md

- Field provenance lives in JSON columns on requisitions and line items rather than a
  separate table, and extraction and check runs share one `llm_runs` table.
- The requisitions table is hand-written rather than TanStack Table, and the UI uses Radix
  primitives with a small token set rather than generated shadcn components.
- The workflow diagram leaves out the "routing field edited during approval" loop for
  legibility; the text beside it describes it.

## Repository

```
backend/app/
  ingest/      email, HTML and PDF parsing, thread split
  privacy/     redaction
  llm/         schema, prompts, OpenAI extractor, validation and grounding, decision checks, cache
  domain/      approval chain, reconciliation, matching, requester, dates, duplicates, workflow
  services/    pipeline, evaluation, routing, orders, serialisation, audit log, live-update bus
  api/         FastAPI routers
backend/tests/ 72 tests, offline (they replay the committed model responses)
frontend/src/  the React app
scripts/       run_all.py (batch evaluation), dev.sh
demo/          an unseen email containing card, IBAN and AHV numbers
```
