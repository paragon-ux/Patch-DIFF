# V07: connected wrapper transaction ownership

Date: 2026-10-21.
Independent candidate: selector_independent_review while inspecting DEV-RUN-002's connected deprecated legacy path.
Base evidence: services/regeneration_service.py at selector PR #4 head2df23ed, request_regeneration explicitly calls session.commit() whenever session.in_transaction() after reading context.

## Triage

Confirmed by source: the condition cannot distinguish the transaction started by the wrapper's own reads from an outer transaction already owned by its caller. It therefore commits caller-owned state before passing the regenerated legacy proposal through the normal locked submit path. This contradicts the objective's explicit global transaction-ownership rule and affects the required Unicode caller-owned commit/rollback acceptance path. It is not a new feature/protocol, general refactor or optional F-item.

Required correction belongs with DEV-RUN-002/V07: establish transaction ownership before reading context. Wrap context lookup and submission in a transaction only if the wrapper entered with none; use the existing outer transaction unchanged otherwise. Remove unconditional commit. Continue through submit_pdcp/_submit; do not create another engine or change guarded application.

## Acceptance

Actual PostgreSQL: caller-owned outer transaction retains ownership after wrapper acceptance/rejection, changes stay invisible to another connection until commit, rollback removes the wrapper attempt and any outer changes, and commit makes the outcome durable. Include invalid Unicode legacy proposal plus ordinary standalone MCP wrapper persistence. Infrastructure errors must propagate to the owner rather than being converted to a successful/domain rejection result.

No merge is authorized. The independent reviewer must recheck the correction and its actual assertions before closure.
