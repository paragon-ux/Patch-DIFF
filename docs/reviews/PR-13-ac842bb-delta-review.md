# PR #13 Delta Review — fixes after the friction re-test

## 1. Review metadata and evidence limits

| Field | Value |
| --- | --- |
| Repository | `paragon-ux/Patch-DIFF` |
| PR | [paragon-ux/Patch-DIFF#13](https://github.com/paragon-ux/Patch-DIFF/pull/13) |
| Review date | 2026-10-22 |
| Reviewer | Claude (Opus 5.5) via Claude Code; the session that authored the change (self-review) |
| Standard | [PR Review Standard v1.1.0](../PR_REVIEW_STANDARD.md) |
| Predecessor | [PR-13-0420dac-category-review.md](PR-13-0420dac-category-review.md), which covers base `16ce338` → `0420dac` and stays as written |
| Delta base | `de6e7c29e1dbafe0caa915e490476a8c6ee5a5a0` (the friction re-test head; `de6e7c2` only added review evidence on top of `0420dac`) |
| Delta head | `ac842bb5afcc6e4dd59f2a1f0312a208dfae0e8d` |
| Delta | 14 files, +72 / −24 (commit `ac842bb`) |
| Trigger | [PR-13-de6e7c2-friction-review.md](PR-13-de6e7c2-friction-review.md): independent re-test, FR-1..FR-20 all fixed, no merge-blocking findings; new friction NF-1..NF-10 |

**Evidence used**

- Source inspection of every delta file, plus the friction report's reproductions. The reviewer confirmed:
  - NF-1, NF-4 and NF-7 by design and from tests;
  - NF-2 and NF-6 from adapter source (literal `ensure_ascii=False` JSON-RPC lines);
  - NF-3 from SQLAlchemy's JSON `None` semantics (`diagnostic_json=None` stores JSON `null`);
  - NF-5 by measuring an in-process scan over 65,536 code points of repetitive text: about 1.2 s and 1,000,000 cells, under concurrent test load;
  - the four documentation mismatches from source.
- Local execution on fresh isolated databases:
  - full pytest at the delta head;
  - `evaluation/offline_eval.py`;
  - a derived live harness, [PR-13-ac842bb-live-verify.py](PR-13-ac842bb-live-verify.py), over real stdio with independent `psql` assertions. Results: [PR-13-ac842bb-live-results.json](PR-13-ac842bb-live-results.json).
- An independent recheck of the delta by the friction reviewer, recorded separately at closing.

**Limits:** self-review; CI for the delta head is recorded at closing; no external MCP host session.

## 2. File-to-category inventory and coverage matrix

| Category | Delta files | Coverage |
| --- | --- | --- |
| ARCH | `docs/usability/friction-followup-decision.md` (amendments section, D14 bullet) | Complete |
| DOC | `CHANGELOG.md`, `docs/HOST_INTEGRATION_GUIDE.md` | Complete |
| SKILL | `.agents/skills/patchdiff-mcp-orchestration/SKILL.md`, `.agents/skills/patchdiff-testing-review/SKILL.md` | Complete |
| MCP | `backend/app/mcp/external_adapter.py`, `docs/MCP_TOOLS.md` | Complete |
| RUN | `docs/PDCP_FORMAT.md` (example UUIDs only) | Complete |
| SVC | `backend/app/services/pdcp_service.py`, `backend/app/services/near_miss_service.py` | Complete |
| DB | None in the delta; the NF-3 fix changes what new accepted rows store (see SVC) | Complete for the persisted effect |
| SCRIPT | None at the delta head; the derived harness is added with this review | Executed |
| TEST | `backend/tests/integration/test_friction_followup_live.py`, `backend/tests/integration/test_friction_followup_stdio.py`, `backend/tests/unit/test_friction_followup.py`, `docs/TEST_MATRIX.md` | Complete |
| DEP | None | Not applicable |

## 3. Architecture-to-implementation trace (delta)

| Decision | Change | Verification |
| --- | --- | --- |
| D14 amended (NF-2, NF-6) | JSON-RPC lines use `json.dumps(response, separators, sort_keys)` with the default ASCII escaping, exactly as at base `16ce338`. The tool-result text inside keeps `_dumps` (literal, with an ASCII fallback for lone surrogates). | Stdio test: the raw line decodes as ASCII, the tool text holds a literal 🌍 and no `\ud83c`, and a document with U+2028/U+2029/U+0085 is one line. Live harness: a cp1252 decode of the line gives identical text. |
| D11 storage (NF-3) | Accepted rows without warnings leave `diagnostic_json` unset (SQL NULL); only rows with warnings set it. | Live test and harness: `diagnostic_json IS NULL` and `jsonb_typeof` null for a plain acceptance; no accepted row anywhere stores JSON `null`. |
| D6 (NF-5) | A window start is abandoned once every cell of a banded row exceeds the threshold. Row minima of edit-distance programs never decrease, so no qualifying window is lost. | The existing pruned-equals-unpruned and banded-equals-unbanded reference tests pass. A new test shows the same ranking with under a third of the unabandoned cells. Measured reach on varied text: full 65,536 code points (was 22,961). |
| D1/D2 guidance (NF-1, NF-7) | The docs say what each warning proves and how to tell a deliberate edit from a mistake; runtime unchanged. | Source reconciliation. |

## 4. Category sections

### ARCH — Architecture and contracts

- **Scope:** decision record amendments.
- **Coverage:** Complete.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:** each NF disposition names the decision it amends or keeps, and the reason. The D14 amendment returns the wire to its base behaviour, so it adds no new compatibility risk.
- **Verdict:** No findings within reviewed scope.

### DOC — Documentation and change records

- **Scope:** CHANGELOG, host guide.
- **Coverage:** Complete.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:**
  - Guide §0 shows `🌍` again.
  - Guide §3 and §10 no longer call warnings mistakes.
  - Guide §8 states the `core.autocrlf` behaviour accurately (LF write-backs of LF-stored files give minimal diffs).
  - CHANGELOG lists the host-visible response changes (NF-4 elision, export `format` refusal, structured argument errors) and the unchanged ASCII wire.
  - The mechanical scan reports 0 real spacing defects, 0 duplicated paragraphs and 0 broken local links.
- **Verdict:** No findings within reviewed scope.

### SKILL — Skills and agent instructions

- **Scope:** two skills.
- **Coverage:** Complete.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:** the wire statement and the SQL NULL rule match the code.
- **Verdict:** No findings within reviewed scope.

### MCP — MCP schemas and public API

- **Scope:** adapter output path; MCP_TOOLS wire, warning and near-miss text.
- **Coverage:** Complete.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:**
  - **MCP-001** (from the predecessor review, = NF-8): still open, deferred to a follow-up. The friction re-test measured a 50-row ledger page over 20 MB of records at 220 ms (base 90 ms).
  - **MCP-002 — An elided `current_context` breaks hosts that read `text` without checking `available` (NF-4).** Status: accepted by decision D8 (kept).
    - Unavailable `current_context` objects were already part of the documented contract at base, with three reasons.
    - The elision removes the duplicate that FR-8 measured at 42% of rejection bytes.
    - It is now listed in the CHANGELOG as a host-visible change.
- **Verification:** stdio integration test and derived harness (§6). `tools/list` size is unchanged by the delta.
- **Verdict:** No blocking findings; one open advisory (MCP-001) and one decision-accepted item (MCP-002).

### RUN — Core runtime, parsing and validation

- **Scope:** PDCP_FORMAT example UUIDs only. No runtime code changed.
- **Coverage:** Complete.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:** source reconciliation.
- **Verdict:** No findings within reviewed scope.

### SVC — Services, orchestration and audit semantics

- **Scope:** `pdcp_service._persist_acceptance`, `near_miss_service.near_misses`.
- **Coverage:** Complete.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:**
  - **SVC-001 — Near misses on highly repetitive text still cost up to about a second of CPU per rejection (residual NF-5).** Status: open, deferred.
    - The exact early abandon widens reach on ordinary text but does not lower the 1,000,000-cell bound.
    - On text where every window shares the query's characters and stays near it for many rows, the cap is reached.
    - MCP_TOOLS documents the latency. A faster exact filter or a smaller cap is a follow-up.
- **Verification:** the NF-3 fix was checked through SQL in the live test and harness. The abandon rule was proven exact from the monotone row-minimum property and checked against the reference implementations in tests.
- **Verdict:** No blocking findings; one advisory P3.

### DB — Database, migrations, replay and concurrency

- **Scope:** the persisted effect of NF-3. No migration changes.
- **Coverage:** Complete.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:** only unmerged PR #13 builds could write the JSON `null` rows, so no released history is affected. Replay ignores `diagnostic_json`. The friction re-test's base-era history checks (keyed recovery, replay after 0002 → 0003) are unaffected by the delta, which touches no recovery or replay code.
- **Verdict:** No findings within reviewed scope.

### SCRIPT — Scripts, evaluation and developer tooling

- **Scope:** the derived harness, added with this review. `PR-13-0420dac-live-verify.py` is left unchanged.
- **Coverage:** Complete.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:** the harness exits non-zero on any failure. Its changed FR-14 check and new NF-2/NF-3/NF-6 checks name the decision they follow.
- **Verdict:** No findings within reviewed scope.

### TEST — Tests and CI

- **Scope:** three test files and TEST_MATRIX.
- **Coverage:** Complete locally; CI is recorded at closing.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:** 1,221 passed (812 unit + 409 live-PostgreSQL integration), 0 failed or skipped. New assertions check SQL-level NULL (not ORM `None`), raw wire bytes, and ranking exactness with a work bound.
- **Verdict:** No findings within reviewed scope.

### DEP — Dependencies, packaging and configuration

- **Scope:** none.
- **Coverage:** Not applicable.
- **P1:** None identified within reviewed scope.
- **P2:** None identified within reviewed scope.
- **P3:** None identified within reviewed scope.
- **Verification:** no dependency or configuration change.
- **Verdict:** Not applicable.

## 5. Cross-category root causes

- **NF-2 and NF-6:** D14 treated "the model sees literal text" and "the wire is literal" as one property. Separating them restores the base wire and keeps FR-14's benefit.
- **NF-3:** a JSON column's Python `None` means JSON `null`. The ORM reads both forms back as `None`, which hid it from the harness and the tests. The tests now check at SQL level.

## 6. Verification record

| Evidence | Revision | Environment | Result |
| --- | --- | --- | --- |
| Full pytest (local) | `ac842bb` | Win 11, Py 3.11.9, PG 16.3, fresh isolated DB | 1,221 passed (812 unit + 409 live-PostgreSQL integration), 0 failed or skipped |
| Offline eval (local) | `ac842bb` | lock venv | exit 0; equivalence OK; tx/3 oracles OK |
| Derived live harness (local) | `ac842bb` | real stdio, `PYTHONIOENCODING=cp1252`, independent `psql`, fresh isolated DB | 235/235 checks |
| Documentation scan (local) | `ac842bb` | active docs and skills vs base `16ce338` | 0 spacing defects, 0 duplicated paragraphs, 0 broken local links |
| CI | PR head and merge commit | GitHub Actions | Recorded at closing |

## 7. Disposition and closure table

**Disposition:** No P0/P1/P2 findings. Every friction finding with a concrete defect is fixed. NF-4 is kept by decision, and the residual parts of NF-5, NF-8 and NF-9/NF-10 are deferred with reasons. Merge remains conditional on green CI and on the independent recheck of this delta finding nothing merge-blocking.

| Friction ID | Re-test severity | Review ID | Disposition | Evidence |
| --- | --- | --- | --- | --- |
| NF-1 | high | — | Fixed (guidance; runtime unchanged) | MCP_TOOLS / guide text |
| NF-2 | high | — | Fixed (D14 amended: ASCII JSON-RPC lines) | stdio test; harness NF-2 checks |
| NF-3 | medium | — | Fixed (SQL NULL) | live test; harness NF-3 checks |
| NF-4 | medium | MCP-002 | Kept by decision D8; documented as host-visible | CHANGELOG |
| NF-5 | medium | SVC-001 | Partly fixed (exact abandon); latency residual deferred | unit test; measurement |
| NF-6 | low | — | Fixed (with NF-2) | stdio test; harness NF-6 check |
| NF-7 | low | — | Fixed (guidance) | MCP_TOOLS text |
| NF-8 | low | MCP-001 | Open, deferred follow-up | predecessor review |
| NF-9 | low | — | Not addressed (remaining response-shape differences) | decision record |
| NF-10 | low | — | Not addressed (predates PR #11) | decision record |
| Doc mismatches (4) | — | — | Fixed | source |
