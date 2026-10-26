# Purchase Requisition Automation

Take-home for BLP: turns purchase-request emails into routed, approvable requisitions.
See [PLAN.md](PLAN.md) for the design; this README grows into the full write-up.

## Run

Requires Python 3.12+ and Node 22+.

```bash
make setup   # venv, dependencies, creates .env from .env.example
make dev     # mock ERP :8080, backend :8000, frontend http://localhost:5173
make test
```
