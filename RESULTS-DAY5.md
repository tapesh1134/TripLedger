# Day 5 verification — 2026-10-04

- **136 tests passed in 14.27 seconds**: 77 inherited regression tests plus 59
  Day 5 tests. The historical image-deferred test now expects opt-in vision to be
  disabled by default.
- Ruff: all checks passed.
- Mypy strict: no issues in 32 source files.
- Fixture validation: 25 reports, all 10 rules, three injection cases, two
  multipage cases. Schema exports regenerated for optional structured line facts.
- Independently constructed expected decisions for all 25 fixtures pass the
  assembler. Removing required findings cannot turn violation cases into accepted
  auto-approvals.
- Real stdio MCP / localhost HTTP regression: the EVAL-24 scripted model first
  emits the blocked receipt citation from the user's run. Validation rejects it;
  correction yields a complete EUR 45 manager-review proposal.
- Tests cover fabricated citations, caps/excess, excess hotel nights, low receipt
  confidence, unavailable attached receipts, image format/size validation, bad or
  unreadable extraction output, inconsistent tax, image request format and safe
  timeout diagnostics.
- Standalone real-MCP receipt smoke with vision disabled returns VISION_DISABLED,
  without calling an external API.

Verification environment: Python 3.12, MCP 1.30.0, Pillow 12.3.0. Project target is
Python 3.11+. requirements-lock.txt records installed verification dependencies.

The vision adapter tests use mocked provider responses; no real OCR/vision accuracy
or corporate gateway image support is claimed. Agent end-to-end tests use scripted
model responses with real MCP and mock backend servers. The 25 expected-decision
tests verify local policy logic, not model success rates. No live corporate API
calls were made in this build. The user's successful Day 4 live runs establish
text/tool support, not Day 5 image support. See DAY5.md for the local checks.

The verifier implements the supplied teaching policy and conservative routing for
unknown facts. It validates citation provenance and structured conditions, not the
semantic truth of all prose or receipt authenticity. Full benchmark scoring and
performance optimization remain later work. No production payments or messages
are sent, and no Windows Application Control setting was changed.

## Reconciliation correction

A live EVAL-24 run exposed a missing-transaction claim despite an available exact
card match. The verifier now rejects a null transaction link when a unique exact
match is available, unused and uncontested, and rejects stale DATA-QUALITY findings
after a valid transaction is linked. Ambiguous and contested matches are not forced.
The prompt explicitly separates missing receipts from missing transactions.
