# Day 3 verification

Verified on 2026-10-04 using Python 3.12 and MCP Python SDK 1.30.0.

| Check | Result |
|---|---|
| Full pytest suite | 69 passed (52 previous + 17 Day 3 cases) |
| Final Day 3 test rerun | 17 passed |
| Ruff | Passed |
| Mypy | Passed, 21 source files; narrowly scoped exception for untyped SDK decorators |
| Real MCP stdio session | Initialize, list and call all nine tools passed |
| Resources | Three resources discovered and read |
| Prompt | One prompt discovered and retrieved |
| Pagination through MCP | Both pages read; 30 transactions overall |
| Uber normalization | Required merchant variants produce a candidate with score 1.0 |
| Invalid input | Safe INVALID_ARGUMENTS envelope; unknown fields rejected |
| Receipt path restrictions | Traversal rejected; synthetic JSON fixture read successfully |
| Dynamic policy data | Updating a temporary Milan cap 120 -> 140 without restart changed hotel excess 52 -> 0 |
| Queue writes | Mock ledger persisted the illustrative decision |

MCP Inspector CLI 2.9.0: tools/list (9), resources/list (3), prompts/list (1),
all three resources/read calls, prompts/get, all nine tools/call requests and the
invalid-argument envelope check passed. These are Inspector CLI checks, not a
claim of a manual UI walkthrough. The script entry point run_mcp.py avoids a
confirmed Inspector CLI argument-forwarding issue with Python's -m flag.

Scope: no autonomous agent or image OCR. `read_receipt` supports synthetic JSON
fixtures; image inputs return IMAGE_EXTRACTION_DEFERRED. Image support is scheduled
for Day 5 in the assignment. Protocol smoke tests use identity FX (EUR to EUR)
without network access; Day 2 contains the recorded public historical FX test.
`--live-fx` enables USD/EUR in the Day 3 smoke command when testing locally.

No API keys, actual .env files, runtime caches, or queued decisions are included
in the delivery. Your custom API credentials are neither required nor used by
Day 3's fixture-based tests.
