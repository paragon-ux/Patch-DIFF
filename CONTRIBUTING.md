# Contributing to PatchDIFF

Thank you for your interest in contributing to PatchDIFF!

PatchDIFF is an MCP-first, server-side deterministic document transaction service. All contributions must respect PatchDIFF's locked architectural invariants and rigorous engineering standards.

---

## 1. Non-Negotiable Invariants

Every change to PatchDIFF must preserve the core transactional boundary:

```text
canonical UTF-8 target text (LF normalized)
+ declarative non-executable transactions (patchdiff-tx/1, patchdiff-tx/2, patchdiff-tx/3, and legacy PDCP 0.2.3)
+ exact deterministic MATCH (all exact occurrences counted)
+ immediate sequential in-memory REPLACE simulation
+ per-target atomic Postgres commit under SELECT ... FOR UPDATE
+ append-only attempt log (accepted and rejected, with lineage and client_request_id idempotency)
+ accepted-only manifest ledger (with runtime-derived span/hash facts)
+ stage-accurate validity reporting and format-specific diagnostics
+ SAVE checkpointing and editing-cycle rotation
+ deterministic replay dispatching on (protocol_version, runtime_version)
```

The core runtime (`backend/app/core/`, `backend/app/pdcp/`) must remain pure and deterministic:
- It must **not** call an LLM, hold model credentials, or make network requests.
- It must **not** depend on FastAPI, SQLAlchemy, or PostgreSQL.
- It must **not** silently repair malformed proposals, guess ambiguous matches, or execute model-generated code.
- It must **not** perform fuzzy, semantic, or AST matching.

---

## 2. Development Setup

### Prerequisites
- Python 3.11+
- Docker & Docker Compose
- PostgreSQL 16+ (via Docker Compose `postgres:16.3-alpine`)
- Node.js 22+ (for external Waymark integrations)

### Local Environment Setup
```bash
# 1. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .\.venv\Scripts\Activate.ps1

# 2. Install pinned dependencies
pip install --upgrade pip
pip install -r requirements.lock
pip install --no-deps -e .

# 3. Start PostgreSQL
docker compose up -d postgres

# 4. Run database migrations through head
export PYTHONPATH=".:backend"
alembic -c backend/app/migrations/alembic.ini upgrade head
```

---

## 3. Testing Rules

Do not claim completion or submit a PR unless all relevant tests pass against live PostgreSQL:

```bash
# 1. Pure runtime unit tests (1,020 tests)
pytest backend/tests/unit -q

# 2. Live PostgreSQL integration tests (561 tests)
export PATCHDIFF_DATABASE_URL="postgresql+psycopg://patchdiff:patchdiff@127.0.0.1:5432/patchdiff"
pytest backend/tests/integration -q

# 3. Offline evaluation (wire payload bytes and verdict equivalence)
python backend/tests/verification/offline_eval.py

# 4. Five-file resident and versioned editor verification
python backend/tests/verification/structural_batch/verify.py --editor-v2 --host-finalize
```

---

## 4. Database Migrations

- All database schema changes require an Alembic migration script under `backend/app/migrations/versions/`.
- Migrations must be strictly additive.
- Migration scripts must verify safe downgrade refusal when newer feature rows exist.
- Always verify the migration cycle before opening a PR:
  ```bash
  alembic -c backend/app/migrations/alembic.ini upgrade head
  alembic -c backend/app/migrations/alembic.ini downgrade -1
  alembic -c backend/app/migrations/alembic.ini upgrade head
  ```

---

## 5. PR Review Standard v1.1.0

All pull requests must undergo a formal category review following [PR Review Standard v1.1.0](docs/standards/PR_REVIEW_STANDARD.md):

1. **Category Mapping:** Every changed file must map to one of the ten primary review categories defined in [PR Review Standard v1.1.0](docs/standards/PR_REVIEW_STANDARD.md): `ARCH`, `DOC`, `SKILL`, `MCP`, `RUN`, `SVC`, `DB`, `SCRIPT`, `TEST`, `DEP`.
2. **Category Coverage Statements:** Each category must have an explicit coverage statement detailing the scope of changes reviewed.
3. **P1/P2/P3 Findings:** Any defect must be categorized by severity:
   - **P1 (Blocker):** State corruption, silent mutation, concurrency bug, broken replay.
   - **P2 (Major):** Contract violation, missing validation, inaccurate diagnostic.
   - **P3 (Minor):** Typo, doc drift, code formatting.
4. **Permanent Review Records:** Completed review reports are committed to `docs/reviews/` and preserved at their reviewed revisions.

---

## 6. Code Style & Conventions

- Follow PEP 8 guidelines.
- Use explicit type annotations for all function and method signatures.
- Preserve all existing comments and docstrings unless explicitly changing behavior.
- Use clickable file links (`file://...`) in documentation and commit messages where applicable.
