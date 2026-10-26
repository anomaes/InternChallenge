# Towards production

What I would change or add before this handles a real customer's purchasing, roughly in
order of importance. None of it is built; the prototype is deliberately local.

## 1. Data protection

- **Contract and region first.** An OpenAI (or Azure OpenAI) agreement with zero data
  retention, EU data residency and a DPA. The Swiss customer's data protection officer
  signs off on which fields leave the company.
- **Redaction stays, and grows.** Today: card numbers, IBANs, AHV numbers and credentials,
  each validated by checksum. Next: pseudonymise personal names before the call
  (`Lukas Frei` → `[PERSON_3]`, mapped back locally), which the requester rule doesn't need
  since it runs on email headers, not model output.
- **Retention policy**: raw emails and attachments are deleted or archived after the
  legal retention period; the local redaction mapping goes with them.
- **Logs** already carry requisition IDs and stage timings only; keep it that way and add
  a check in CI that fails on email addresses or amounts in log statements.

## 2. Identity and authorisation

- SSO (Entra ID or Google) instead of the approver ID in the URL. Approver links in
  notification emails become signed, expiring, single-use tokens.
- Roles: purchasing clerk, approver, admin. An approver sees only requisitions where they
  hold a step. Every action in the audit log carries the real user, not "clerk".
- Deputies and holiday cover (out of scope here): an absence calendar per approver, and
  the `deputy_for` relation in the master data used as the stand-in, recorded as such.

## 3. Ten times the volume (1,000 to 2,000 emails a day)

The numbers are small for a computer: 2,000 emails a day is about one every 15 seconds
over a working day, and extraction takes about 10 seconds per email. The work is making
it robust, not fast.

- **Ingestion**: a mailbox connector (Microsoft Graph or IMAP with idempotent message-ID
  tracking) instead of the simulator. Every email is persisted before processing.
- **Queue**: the pipeline moves out of the web process into workers (a Postgres-backed
  queue is enough at this volume), with retries, a dead-letter state that lands in Needs
  review, and per-stage timeouts. The stages already are separate functions.
- **Database**: Postgres instead of SQLite; the SQLModel models port unchanged. Row-level
  locking around approval decisions so two clicks can't both advance a chain.
- **LLM throughput and cost**: rate-limit handling with backoff; the Batch API for
  non-urgent re-processing; prompt caching for the shared instructions.
- **Master data** syncs from the ERP nightly instead of a JSON file; the system only reads
  its own copy, as now.

## 4. Correctness over time

- **An accuracy harness**: hand-labelled expected values for a growing set of real emails,
  scored per field on every prompt, model or rule change, in CI. `scripts/run_all.py` is
  the start of this; it lacks the labels.
- **Monitoring**: share of requisitions that need review, by reason; clerk corrections
  per field (a rising rate means the extraction is drifting); time from arrival to order;
  LLM error and retry rates. Alert on sudden changes.
- **Feedback loop**: clerk corrections are already in the audit log. Use them to find
  weak suppliers or document templates, add supplier aliases, and tune the prompt.
- **Exchange rates** from the daily ECB feed, with the rate and its date stored on each
  requisition (already stored per requisition here).

## 5. Integrations

- The real ERP API: idempotent submission is already in place. Add reconciliation (a
  nightly check that every ORDERED requisition has its PO in the ERP) and handle
  asynchronous confirmations.
- Notifications by email and Teams, from the outbox table that already exists, with
  reminders and escalation when an approver doesn't act within N days.
- Supplier onboarding: a clerk-created supplier goes to a vendor-master workflow
  (bank details verification, sanctions screening) before the first order.

## 6. Operations

- Containerised deployment, one backend image and a static frontend, behind the
  customer's reverse proxy. Secrets in a vault, not `.env`.
- Backups and a restore drill for the database; the raw emails make every requisition
  reproducible.
- Multi-tenancy (out of scope here): one database schema per customer, so one customer's
  data never shares tables with another's.
