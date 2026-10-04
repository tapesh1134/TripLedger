# Day 6 verification — 2026-10-04

- Full regression: **170 tests passed in 17.83 seconds** (136 inherited, 34 new).
- Ruff: all checks passed.
- Mypy strict: no issues in 35 source files, including the new runner and scorer.
- All 25 independently constructed reference outcomes pass the scoring rules.
- Tests verify incomplete fallbacks fail, wrong totals and unsafe approvals are
  detected, rule/line errors and incomplete pagination fail, unknown usage remains
  flagged, pending cases remain in denominators, retries preserve first-pass scores
  and usage, offline scoring needs no API key, and changed configuration blocks resume.
- Runner test uses mocked reviews to exercise save, skip, retry and resume paths.
  Existing real-MCP / localhost-mock integration tests remain passing.

No corporate API calls were made for this build. Reference-output and mocked-runner
tests are not live LLM accuracy benchmarks. No fabricated measured model scores are
included. Run the commands in DAY6.md to generate your actual results.

Verified in Python 3.12 with the dependencies in requirements-lock.txt; source
project targets Python 3.11+. Windows commands are supplied, but Windows was not
executed here. No corporate Application Control settings were changed.

## EVAL-21 validation-recovery correction

The user's live run reached the 12-step limit after an unsupported top-level
policy_version field and repeated reconciliation-delta validation errors. The
updated prompt explains metadata placement and separates card matching differences
from reimbursement deductions. Validation feedback now includes the exact expected
matching delta and transaction ID. No policy rule, scoring label or step budget
was relaxed. The new regression checks rejection of an incorrect EUR 20 matching
delta, acceptance of the corrected zero delta, and preservation of the EUR 20
policy disallowance. Live success of the updated prompt still needs the targeted
EVAL-21 run; preserve the original 96% full-suite first-pass result separately.
