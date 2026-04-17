# SwaggerTest — Project Handoff

## Overview

SwaggerTest is a Python CLI tool and library that discovers OpenAPI specs from Swagger UI pages and generates structured test cases from Rally tickets using OpenAI gpt-5-mini. It operates in two distinct modes:

1. **GET Endpoint Testing** — Discovers the OpenAPI spec from a Swagger UI URL, fires real HTTP GET requests against every endpoint, validates responses against declared schemas, and produces a structured JSON report.

2. **Rally-Driven Test Generation** — Reads Rally ticket exports (CSV/Excel), uses an LLM to match tickets to API endpoints, generates structured test cases with assertions and edge cases, and optionally executes them against a staging server.

It is designed for CI pipelines, QA engineers, and backend developers who need fast feedback on spec-vs-reality drift.

---

## Tech Stack

- **Language:** Python 3.11+
- **HTTP Client:** `httpx` (async-capable, timeout/redirect handling)
- **HTML Parsing:** `beautifulsoup4` (Swagger UI scraping)
- **Spec Resolution:** `prance` (`$ref` resolution), `openapi-spec-validator` (validation)
- **Schema Validation:** `jsonschema` (lenient mode — only required fields checked)
- **YAML Parsing:** `pyyaml` (config and spec YAML support)
- **CLI Framework:** `typer`
- **LLM:** OpenAI `gpt-5-mini` via official `openai` SDK
- **Excel Support:** `openpyxl`
- **Environment:** `python-dotenv` (config file loading)
- **Testing:** `pytest` + `respx` (HTTP mocking in tests)

---

## Project Structure

```
Autonomous-QA/
├── swaggertest/
│   ├── __init__.py         # Public API exports + __version__
│   ├── cli.py              # Typer CLI: parse, run, match, generate commands
│   ├── config.py           # Config dataclasses, precedence resolution, seed params
│   ├── discoverer.py       # Swagger UI HTML scraping, 4-strategy spec URL extraction
│   ├── parser.py           # OpenAPI spec fetch/parse, from_file(), Endpoint dataclass
│   ├── runner.py           # Runner (GET loop) + TestCaseRunner (all HTTP methods)
│   ├── validator.py        # Response validation: status code + lenient schema check
│   ├── reporter.py          # JSON report builder with meta counts + has_failures
│   ├── models.py            # Dataclasses: TestCase, TestAssertion, TicketMatch
│   ├── ticket_reader.py     # CSV/Excel → list[dict], UTF-8-BOM decoding
│   ├── llm_client.py        # OpenAI wrapper with token tracking + usage_summary()
│   ├── matcher.py           # LLM ticket→endpoint matching
│   ├── generator.py         # LLM test case generation with token budget guard
│   └── testcase_io.py       # JSON save/load for test_cases.json
├── tests/
│   ├── test_discoverer.py   # 3 tests: HTML extraction, fallback paths, error cases
│   ├── test_config.py       # 4 tests: precedence, missing BASE_URL, seed params
│   ├── test_validator.py     # 5 tests: schema pass/fail, status code, no-schema
│   └── test_reporter.py      # 3 tests: meta counts, file save, has_failures
├── .swaggertest.yaml        # Per-project config (checked in)
├── .env                     # Per-user config (gitignored)
├── pyproject.toml           # Project metadata + dependencies
└── README.md
```

---

## How It Works

### Mode 1: GET Endpoint Testing

**Data flow:**

```
Swagger UI URL
    │
    ▼
discoverer.py — 4-strategy scraping → raw spec URL
    │
    ▼
parser.py — fetch + YAML/JSON detect + prance $ref resolve
         + openapi-spec-validator → list[Endpoint]
    │
    ▼
runner.py — for each GET endpoint:
    ├── resolve path/query params from seed_params_file
    ├── inject auth (Bearer / API key / Basic)
    ├── httpx GET with timeout + delay
    └── EndpointResult(status, body, timing)
         │
         ▼
validator.py — check 200 + lenient JSON schema → passed/failed/skipped
         │
         ▼
reporter.py — build JSON report with meta counts
```

**Spec Discovery strategies (in priority order):**
1. Regex match on `SwaggerUIBundle({ url: "..." })` in inline JS
2. `<meta name="swagger-config">` tag extraction
3. Fetch `configUrl` JSON from the URL found in JS
4. Probe well-known paths: `/v3/api-docs`, `/swagger.json`, `/api-docs`

**Schema validation is lenient** — only required fields and their types are checked. Extra fields in the response are ignored and do not cause failures.

---

### Mode 2: Rally-Driven Test Generation

**Data flow:**

```
Local OpenAPI spec file + Rally CSV/Excel
    │
    ▼
ticket_reader.py — CSV (UTF-8-BOM) or Excel → list[dict]
    │
    ▼
parser.py — from_file() → list[Endpoint]
    │
    ▼
matcher.py (LLM call) — endpoint catalog + raw ticket rows
    └── LLM identifies ID/title columns, returns TicketMatch list
        (tickets with no valid endpoint matches → warned, excluded)
    │
    ▼
generator.py (LLM call) — ticket details + matched endpoint schemas
    └── LLM generates 3-7 test cases per ticket:
        happy path, edge cases, negative cases, bug repro
        Token budget guard: truncates if >80k tokens
    │
    ▼
testcase_io.py → test_cases.json (envelope format with LLM usage)
    │
    ▼ (optional)
runner.py TestCaseRunner — execute against staging, evaluate assertions
```

**Test case output envelope:**

```json
{
  "generated_at": "...",
  "generator_version": "1.0.0",
  "source": { "ticket_file": "...", "spec_file": "..." },
  "llm_usage": { "input_tokens": N, "output_tokens": N, "estimated_cost_usd": N },
  "test_cases": [
    {
      "name": "...",
      "description": "...",
      "source_ticket": "US1042",
      "target_endpoints": ["PUT /members/{id}/pcp"],
      "method": "PUT",
      "path": "/members/{id}/pcp",
      "path_params": {"id": "12345"},
      "query_params": {},
      "headers": {"Content-Type": "application/json"},
      "request_body": {"pcpId": "doc-789"},
      "expected_status_code": 200,
      "assertions": [
        {"type": "json_path", "expression": "$.pcpId", "expected": "doc-789", "comparator": "equals"}
      ],
      "edge_cases": ["What if pcpId is null?"],
      "tags": ["pcp", "members"],
      "priority": "medium"
    }
  ]
}
```

---

## Configuration Precedence

```
CLI flags > .env > .swaggertest.yaml
```

`BASE_URL` and `API_TOKEN` are the two critical values. The tool hard-fails if `BASE_URL` is missing when needed. All config sources are checked; CLI flags always win.

---

## Current State

### What works:
- GET endpoint discovery and testing end-to-end
- Rally ticket CSV and Excel parsing
- LLM-powered ticket→endpoint matching (LLM identifies ticket ID/title columns itself)
- LLM-powered test case generation with token budget guard
- Test case execution with assertion evaluation
- JSON schema validation in lenient mode
- Full CLI with 4 commands: `parse`, `run`, `match`, `generate`
- Library API for programmatic usage
- 15 tests covering core modules

### Known rough edges:
- No OAuth2 flow support
- No HTML or pytest output format
- No test ordering or dependency chaining
- No SLA / performance threshold checks
- No mutating method (POST/PUT/PATCH) execution in `run` command (only `generate --execute` supports it)
- Only `gpt-5-mini` is used — no model switch capability
- No retries or circuit breakers on failed API calls
- No test case versioning or diffing

---

## Improvements

### 1. Property-Based Test Generation
**What to do:** Modify `generator.py` to generate property-based test cases in addition to example-based ones. For each endpoint with a schema, instruct the LLM to generate tests that verify invariants: "field X should always be a positive integer", "field Y should never be null when status is active", "sum of quantities should not exceed inventory count". Store these as `assertions` with a new type like `assertion_type: "invariant"`.

**Why it matters:** Example-based tests cover happy paths. Property-based tests catch entire classes of bugs. Staff engineers think in invariants and edge cases, not just examples.

**Files likely to touch:** `swaggertest/models.py`, `swaggertest/generator.py`, `swaggertest/runner.py`, `swaggertest/validator.py`

**Verification:** Add 3 new test cases to `tests/` that verify invariant assertions are serialized and evaluated correctly.

---

### 2. Test Prioritization Using Historical Failure Data
**What to do:** Extend the `matcher.py` and `generator.py` pipeline to accept a `failure_history.json` file (maps endpoint→historical failure rate). Add a new CLI flag `--failure-history` to `generate`. When scoring and selecting test cases, weight endpoints with high historical failure rates higher. Generate more edge cases for those endpoints.

In `matcher.py`, add a step after LLM matching that re-weights matches using the failure history. Pass the re-weighted list to `generator.py` with an additional `priority_override` field.

**Why it matters:** Running 500 tests on every PR is slow. Prioritizing by historical failure turns a blunt instrument into a surgical one. This is the kind of data-informed thinking that separates Staff from Senior.

**Files likely to touch:** `swaggertest/matcher.py`, `swaggertest/generator.py`, `swaggertest/cli.py`, `swaggertest/config.py`

**Verification:** Run `swaggertest match` with `--failure-history` on the test dataset and verify high-failure endpoints appear first in the match list.

---

### 3. API Contract Testing — Spec vs Response Validation
**What to do:** Add a new validator mode in `validator.py` that compares the actual response shape against the OpenAPI schema more strictly. Currently it uses lenient mode (ignores extra fields). Add a `--strict-schema` flag to `run` that enables strict validation. This checks: field types match exactly, enums are respected, numeric bounds are checked, required fields are present.

Also add a `diff` output mode that shows exactly which fields are missing, extra, or type-mismatched compared to the spec — not just a pass/fail.

**Why it matters:** The most dangerous API bugs are silent — the API returns data in the wrong shape and tests pass because of lenient validation. Strict schema checking catches these. Staff engineers care about catching the bugs that sneak into production.

**Files likely to touch:** `swaggertest/validator.py`, `swaggertest/reporter.py`, `swaggertest/cli.py`, `swaggertest/config.py`

**Verification:** Create a test spec with a known type mismatch and verify `--strict-schema` correctly flags it while default mode passes it.

---

### 4. OpenAPI 3.1+ Full JSON Schema Validation
**What to do:** The current `jsonschema` validator handles OpenAPI 2.x and 3.0-style schemas well but lacks support for OpenAPI 3.1's `prefixItems` (array tuple validation) and `type: "null"` combinations. Add a JSON Schema 2019-09+ validator adapter in `validator.py` using `jsonschema>=4.0` with `json-schema-spec` for OpenAPI 3.1 compliance.

Add a `spec_version` field to the `Report` output so consumers know which spec dialect was used.

**Why it matters:** OpenAPI 3.1 is increasingly common. If the tool silently skips valid schema checks for 3.1 specs, it produces false confidence. This is a correctness issue that matters for CI gatekeeping.

**Files likely to touch:** `swaggertest/validator.py`, `swaggertest/parser.py`, `swaggertest/reporter.py`, `pyproject.toml`

**Verification:** Test against a real OpenAPI 3.1 spec with `prefixItems` and verify tuple validation is applied.

---

### 5. Test Dependency Graph and Ordering
**What to do:** Build a directed graph of test dependencies from the `target_endpoints` in generated test cases. Use a topological sort to order execution so dependent endpoints run after their dependencies (e.g., `POST /orders` before `GET /orders/{id}` before `PUT /orders/{id}/cancel`).

Add a `--detect-dependencies` flag to `generate` that builds this graph using the LLM to identify implicit dependencies (e.g., resource creation before resource retrieval). Store dependencies in the `TestCase` model as an optional `depends_on` list.

Modify `TestCaseRunner` to respect the sorted order and skip tests whose dependencies failed.

**Why it matters:** Test execution order matters. A test for `GET /orders/{id}` that runs before `POST /orders` will always fail on a fresh environment. This is production-grade CI thinking.

**Files likely to touch:** `swaggertest/models.py`, `swaggertest/generator.py`, `swaggertest/runner.py`, `swaggertest/cli.py`

**Verification:** Generate test cases for a CRUD resource and verify the execution order puts POST before GET before PUT before DELETE.

---

### 6. HTML Report Generation
**What to do:** Add a new reporter format `html` alongside the existing `json`. Build `reporter_html.py` that generates a self-contained HTML report with:
- Summary dashboard (pass/fail/skipped counts, pass rate percentage)
- Color-coded endpoint table (green/red/yellow)
- Expandable rows showing request/response diff for each failure
- Filter bar to show only failures or specific tags
- A "Re-run" button that copies the `swaggertest run` command with the same config

Use a single HTML file with inline CSS/JS (no external dependencies for portability).

**Why it matters:** JSON reports are great for machines. HTML reports are what get looked at in sprint reviews and post-mortems. A good engineer makes the information usable by non-engineers too.

**Files likely to touch:** `swaggertest/reporter_html.py`, `swaggertest/cli.py`, `swaggertest/config.py`, new `tests/test_reporter_html.py`

**Verification:** Generate an HTML report from an existing JSON report and verify it renders correctly in Chrome.

---

### 7. CI/CD Integration — GitHub Actions + Jira Webhook
**What to do:** Create a `.github/workflows/` directory with two workflows:

`api-test.yml`: Runs `swaggertest run` on every PR comment and posts the JSON report as a GitHub PR check. Uses `upload-artifact` to store the report.

`test-case-sync.yml`: After `swaggertest generate --execute`, if any tests fail, automatically create a Jira ticket (via Jira API) with the failed test details, endpoint, and error message as the description.

Add `jira_webhook` config section to `.swaggertest.yaml` for the Jira integration.

**Why it matters:** The value of a testing tool is only realized when it actually runs in CI and its results reach the people who act on them. Staff engineers close the loop between testing and issue tracking.

**Files likely to touch:** `.github/workflows/api-test.yml` (new), `.github/workflows/test-case-sync.yml` (new), `swaggertest/cli.py`, `.swaggertest.yaml`

**Verification:** Create a PR with a breaking API change and verify the GitHub Actions check appears and the JSON report is uploaded as an artifact.

---

### 8. Self-Healing Test Cases Using Response Diffs
**What to do:** After a test case fails in `generate --execute`, instead of just reporting it, add a self-healing step: take the actual response body, diff it against the declared schema, and use an LLM to suggest updated assertions.

In `runner.py`, after a `TestCaseRunner` run completes with failures, call a new `self_healer.py` function that:
1. Extracts the actual response values for each failed assertion
2. Asks the LLM: "Given the actual response, what are the correct assertions?"
3. Produces a revised `test_cases.json` with corrected assertions

Store healed test cases in a separate `test_cases.healed.json` alongside the original.

**Why it matters:** Test suites rot. Assertions become stale as APIs evolve. Self-healing reduces the maintenance burden and makes the tool actually usable in fast-moving teams. This is advanced agentic tooling thinking.

**Files likely to touch:** `swaggertest/self_healer.py` (new), `swaggertest/runner.py`, `swaggertest/llm_client.py`, `swaggertest/cli.py`

**Verification:** Introduce a breaking change in a test spec, run the full generate→heal pipeline, and verify the healed assertions match the new response shape.

---

### 9. Rate Limiting + Retry with Exponential Backoff
**What to do:** The current `Runner` fires requests with a fixed `request_delay_ms` delay. This is naive — it doesn't handle 429 rate limit responses gracefully. Add adaptive rate limiting to `runner.py`:

1. On 429 response, read `Retry-After` header if present, else use exponential backoff starting at 1s
2. Cap the maximum retry delay at 60s and the maximum retry count at 5
3. On 5 consecutive 429s, fail the endpoint with a `rate_limited` status rather than retrying indefinitely
4. Add `--max-retries` and `--retry-cap-seconds` flags to the CLI

Add a `rate_limit_stats` field to the JSON report showing how many endpoints triggered rate limit handling.

**Why it matters:** Hitting rate limits in CI is common and destructive — a single 429 can invalidate an entire test run. Proper retry logic is fundamental infrastructure code. Staff engineers write systems that handle the hostile reality of networked services.

**Files likely to touch:** `swaggertest/runner.py`, `swaggertest/reporter.py`, `swaggertest/config.py`, `swaggertest/cli.py`

**Verification:** Run against a server that returns 429 on the 3rd request and verify: retries happen, delay grows exponentially, and the report shows correct stats.

---

### 10. Parallel Test Execution
**What to do:** Currently `Runner` and `TestCaseRunner` iterate sequentially. For large APIs with 100+ endpoints, this is slow. Add async execution using `httpx.AsyncClient` with a configurable concurrency limit.

In `runner.py`, add an `AsyncRunner` class alongside the existing sync `Runner`. Use a semaphore to cap concurrent requests (configurable via `max_concurrency` in config). Preserve the same validation, reporting, and retry logic.

Add `--async` and `--concurrency` flags to the CLI. Default concurrency to 10.

**Why it matters:** Speed is a feature. A test suite that takes 20 minutes is one that developers stop running. Staff engineers know that a test suite that isn't fast isn't actually used.

**Files likely to touch:** `swaggertest/runner.py`, `swaggertest/cli.py`, `swaggertest/config.py`, `tests/test_runner.py` (add async tests)

**Verification:** Run a 50-endpoint spec in both sync and async mode and verify: async completes in roughly 1/Nth the time (where N is concurrency), and the final report is identical.
