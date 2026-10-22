# Goal F merged-main baseline and existing-fix closures

Baseline executed on 2026-10-21 at main 2ee7ce46461598d71f0f9b2570ad7d9d3aa03d10, before Goal F product edits. Branch: feature/goal-f-rejection-context. Accepted authority: accepted/Devin-Goal-F.md revision 2 and accepted/AUTHORITY.json. F08/F13/F14 below close existing fixes with evidence; they are not new feature implementations.

## Actual baseline execution

- Python 3.11.9 from the original checkout's .venv, with PYTHONPATH=backend and working directory set to this worktree, so imports resolve to merged main.
- Fresh database patchdiff_goal_f_baseline_20261021. Alembic upgrade head, downgrade -1 and upgrade head completed. Populated migration rehearsal and downgrade refusal also ran in the integration suite.
- Command: python -m pytest backend/tests/unit backend/tests/integration -o addopts='' -q --junitxml=docs/usability/BASELINE-junit.xml. Result: 842 passed, nine warnings, 116.33 seconds. JUnit independently counts 617 unit and 225 integration, zero failures/errors/skips. JUnit SHA-256: 8215ef2b27b3a2114d3c39b90580ee5baa73932e211f321b33bb12f727bdfa79.
- python evaluation/offline_eval.py: shared-applier equivalence OK, including the explicitly allowed legacy delimiter rejection/typed acceptance exception. This measures payload bytes, not model success or tokens.
- Separate manual outside-pytest public stdio/SQL check: BASELINE-live-verify.py against patchdiff_goal_f_baseline_manual_20261021. Four absent/cp1252 by raw/escaped Unicode profiles passed, including exact stored content/version/audit/ledger state, keyed recovery, SAVE/replay/export, and malformed-wire nonmutation. BASELINE-live-results.json pins executed_head to 2ee7ce4 and records source digests/raw bytes. This is subprocess evidence, not an installed-host configuration change.

Artifacts: BASELINE-suite.txt, BASELINE-junit.xml, BASELINE-offline.txt, BASELINE-manual.txt and BASELINE-live-results.json in this directory. No additional baseline rerun was needed for the subsequent read-only Gemini report assessment.

## F08: closed with evidence

Original DEV-RUN-001 production fix ecd0dfa4573b6f4284e5d102d23ff9dc1310e711; final tested material 3d4daec2361c87615e3dc20bc5341a90cc0b75cf; PR #4 merge d950d92b912b8e07a4219871019019ca07e67e5f. All are ancestors of the executed main baseline.

Passed in BASELINE-junit.xml:

- backend/tests/unit/test_selector_profiles.py: test_selector_constraint_matrix (208 cases), test_old_profiles_preserve_ignored_singleton_selectors (12), test_profile_semantics_are_distinct_and_unknown_profiles_fail_closed, test_advisory_region_hint_still_allows_a_singleton.
- backend/tests/integration/test_selector_profiles_live.py: test_singleton_constraint_rejection_is_durable_without_materialization (8), test_ignored_selector_history_replays_under_its_recorded_profile (6), test_real_stdio_rejects_singleton_selector_and_exposes_persisted_attempt.

These verify current singleton constraints across typed/legacy and immediate/sequential buffers, atomic rejection and persisted audit, public stdio, and unchanged older-profile selector behavior/hashes/fingerprints. Total selected evidence: 222 unit plus 15 live integration cases.

Historical outside-pytest evidence and independent review remain docs/remediation/DEV-RUN-001-{tests.json,live.json,review.md,CI.json}. Manual material pin 3d4daec records typed/legacy public examples, three rejections, one acceptance/ledger entry, keyed recovery and replay. Original CI 39542822860 executed generated merge 3ee9105, with 403 unit/153 integration; it is not the current main run.

## F13: closed with evidence

DEV-MCP-002 production 3b122dfa3d22e9e5d62c381131292417506d9bd0; final tests 69f6a646270ab74aba54eca635e2a6ea9cca968a; PR #8 merge 3b1c032500d074e8a38096b33cbb067c06744862. All are ancestors of the executed baseline.

Passed unit evidence in backend/tests/unit/test_mcp_arguments_paging.py includes test_history_page_boundaries_and_display_order (10), test_history_defaults_and_caps (12), integer/boolean/filter/status/target validation families, and test_discovery_agrees_with_bounds_nullable_history_and_legacy_key_lookup. Tests assert effective limit+1 query lookahead, has_more and returned exclusive cursor, rather than merely checking response keys.

Six passed live cases in backend/tests/integration/test_mcp_history_paging_live.py:

- test_both_histories_traverse_gaps_and_ignore_newer_insertions_between_calls
- test_status_hash_key_and_cursor_filters_apply_before_page_lookahead
- test_existing_empty_and_missing_targets_have_terminal_empty_pages (two handlers)
- test_exact_stored_legacy_key_is_queryable_without_new_submission_key_validation
- test_real_stdio_history_pages_keep_both_orders_and_cursor_metadata

Coverage preserves descending attempts, ascending display within each newest ledger page, next_sequence equal to the minimum returned sequence and exclusive before_sequence traversal, filters before lookahead, intervening insertion exclusion, bounded termination, and no duplicates/skips.

Historical outside-pytest material: docs/remediation/DEV-MCP-001-002-{tests.json,live.json,review.md,CI.json}. Manual production pin 3b122df records both stdio history pages, filters and complete traversal. Original CI 39572642874 executed b0444e27888ce86407127620974387a1517b280d, with 613 unit/221 integration.

## F14: closed with evidence

DEV-MCP-001 shares the production/final-test/PR #8 pins above. Passed focused unit cases in test_mcp_arguments_paging.py:

- test_invalid_context_rejects_before_querying (10): -1, -100, True, False, None, string, integer-valued/fractional float, list and object.
- test_context_zero_and_cap_preserve_exact_search (6): 0/1/40/400 retained and 401/10000 capped to 400.
- test_default_context_is_40_and_tool_routing_keeps_domain_errors.
- Shared discovery test asserts integer/minimum-zero/default-40 schema. The real-stdio history test sends context_chars=-1 and verifies invalid_argument.

Historical manual production pin 3b122df separately records zero_context=true and boolean_context_invalid=true. No new context behavior or tests were added for this evidence closure.

## Independent recheck and limits

Default-model read-only agent f01_contract_exploration independently mapped the exact fix/test ancestry and passed baseline JUnit cases above after consolidation; it made no edits or reruns. Prior independent reviews are preserved in the cited remediation records. No historical review file was changed.

Consolidated PR #1 CI 39663238218 executed generated merge 47bc5f7f166104fd42fa49dd095aff1ef67ce894, with 617 unit/225 integration and offline equivalence OK (integration/PR-1-CI-39663238218.txt). The actual main merge is 2ee7ce4; do not conflate these SHAs. integration/CONSOLIDATION_RECHECK.md records the matching trees and category review.

The new baseline manual helper is transport-oriented, and does not independently rerun the selector matrix or multipage-history scenarios outside pytest on main. Current-main evidence for those scenarios is the actual passed PostgreSQL/stdio integration cases; their separate outside-pytest observations remain pinned to the original fixes. This distinction prevents upgrading historical manual evidence into an unperformed new run. The accepted closures are supported without recoding the existing fixes.

F01/F12/F10 and later accepted features remain pending until their own implementation, live evidence and independent PR review pass. These closures do not authorize merging a new feature PR.
