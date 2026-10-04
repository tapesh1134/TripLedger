# Day 1 verification

Scope: Day 1 foundation only, using Python 3.12.14.

| Check | Result |
|---|---|
| `python -m pytest -q` | 36 tests passed |
| `python -m mypy` | Passed; 15 source files |
| `python -m ruff check .` | Passed |
| Report / decision examples | Schema validation passed |
| Example hotel calculation | EUR 494.40 allowed; EUR 52.00 disallowed |
| Whole-line disallowance | Covered by passing unit tests |
| Provider retries, auth headers, chat and embedding response handling | Offline mocked HTTP tests passed |
| Real custom LLM call and actual token counts | Pending user endpoint, model and API key |
| Real custom embedding call | Pending user endpoint, model and API key; optional for Day 1 |

Run the documented smoke commands after editing `.env`. Offline provider tests
are not evidence of a successful real provider call. No real API credential was
used, no paid inference call was made, and no report was sent to an API.

Full-project NFR benchmarks, 25-report evaluation, policy accuracy, autonomous
decisions and MCP Inspector checks belong to later days and have not been run.
