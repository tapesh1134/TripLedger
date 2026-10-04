# Day 2 verification

Verified using Python 3.12.14 on 2026-10-03 UTC (2026-10-04 India).

| Check | Result |
|---|---|
| Full pytest suite | 52 passed; includes original 36 Day 1 tests |
| Ruff | All checks passed |
| Mypy | No issues in 17 source files |
| Four HTTP mocks | Started and exercised over real loopback HTTP |
| Pagination | 20 items on page one; 30 overall; hotel found on page two |
| Injected card failure | Retry demo completed 12 calls; recovered from HTTP 503 |
| Ledger persistence | SQLite queue; duplicate posts idempotent; conflicting update returns 409 |
| FX offline tests | Exact rounding, durable cache, source/date, invalid response, outages |
| Live Frankfurter call | USD 100 on 2026-04-09 -> EUR 85.58; rate 0.8558 |
| Live returned rate date | 2026-04-09 |
| Second FX call | cached=true; identical rate and result |
| Local command smoke checks | demo, retry-demo and queue-example passed |

Live FX source:
https://api.frankfurter.dev/v1/2026-04-09?base=USD&symbols=EUR

No cached rates or queued demo decisions are shipped in the ZIP: runtime storage
is generated on first use. Tests use separate temporary storage and fake FX rates.
Live provider data can be corrected subsequently; the rate above records this run.

The execution tool isolates networking between separate tool sessions. CLI checks
therefore started the four server processes and client commands within one session;
all requests still went over HTTP. On a normal Windows machine the two-terminal
workflow uses the same localhost network.

Your custom model keys were not available here. Your conversation showed successful
chat and embedding calls on your Windows machine; these were not repeated in this
environment. Your Windows App Control block on mypy remains a separate local issue.

Days 3–7 MCP transport, resources, fuzzy matching, autonomous agent, assembler,
receipt vision and full 25-report evaluation are outside this delivery.
