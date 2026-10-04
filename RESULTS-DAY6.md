# Day 6 verification — 2026-10-04

- Full regression: **169 tests passed in 17.00 seconds** (136 inherited, 33 new).
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
