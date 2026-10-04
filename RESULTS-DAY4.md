# Day 4 verification — 2026-10-04

- Full regression suite: **77 passed in 13.23 seconds** (69 existing + 8 Day 4 tests).
- Ruff: all checks passed.
- Mypy strict: no issues in 27 source files, including the new agent package.
- Fixture validator: 25 reports, all 10 rules, 3 injection cases, 2 multipage cases;
  reports and attached JSON receipts validate against their contracts.
- Real stdio MCP and localhost HTTP mocks exercised with scripted model responses:
  clean EUR 20 review, alternative tool ordering, optional queue write, 21-line
  pagination, invalid-total feedback and correction, unfinished-page rejection,
  invented transaction rejection, repeated-call limit, provider failure, blocked
  model save/out-of-report reads and null totals for incomplete runs.
- Existing Day 1–3 calculator, adapters, retry, FX/cache, matching, queue,
  resource hot-reload and all-nine-tools tests remain passing.

The scripted model exists only in tests. Production `app.day4` always calls the
configured custom API. These tests verify orchestration and checks; they do not
measure autonomous model decision accuracy, injection resistance, calibration,
provider latency or live model tool compatibility. The corporate API was not
called here because its credentials are not available. Run the clean and multipage
commands in DAY4.md to check your gateway locally.

The evaluation labels are prepared, not scored. Full independent policy/evidence
verification and receipt vision remain later work. The Day 4 assembler checks
structure and basic consistency but does not independently reconstruct every
policy finding or validate all model-supplied caps. Synthetic teaching use only.

Verified on Python 3.12 with MCP 1.30.0. The project targets Python 3.11+.
`requirements-lock.txt` records this verification environment; Windows users may
install `requirements-dev.txt` as documented. No Windows execution or corporate
App Control policy change was performed here.
