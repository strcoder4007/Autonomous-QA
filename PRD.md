# PRD: SwaggerTest — API Test Tool

---

## 1. Overview

Reads Rally ticket exports (CSV/Excel), uses OpenAI gpt-5-mini to match tickets to API endpoints, generates structured test cases with realistic test data, and optionally executes them.

Usable as both a CLI tool and a Python library.

---

## 2. Goals

- Reduce manual effort of verifying API contracts after changes
- Give the team a fast feedback loop on spec-vs-reality drift
- Generate test cases directly from Rally stories and defects, preserving business intent
- Produce machine-readable JSON outputs suitable for CI artifact storage and downstream tooling

---

## 3. Users

| User | Context |
|------|---------|
| Backend developer | Runs the tool locally against a staging server to verify a new endpoint |
| QA engineer | Exports Rally tickets and generates a test plan from them |
| CI pipeline | Runs the tool on every PR to detect spec drift or broken endpoints |

---

## 4. Configuration & Precedence

All config is resolved in this strict precedence order (highest to lowest):

| Source | Example |
|--------|---------|
| CLI flag | `--base-url https://staging.example.com` |
| `.env` file | `BASE_URL=https://staging.example.com` |
| `.swaggertest.yaml` | `base_url: https://staging.example.com` |

Config loading is always permissive — commands that require `base_url` (e.g. `run`, `generate --execute`) validate its presence themselves and fail with a clear error message.

**`.env` file (per-user, gitignored):**
```env
BASE_URL=https://staging.example.com
API_TOKEN=your-token-here
OPENAI_API_KEY=sk-...
```

**`.swaggertest.yaml` (per-project, checked in):**
```yaml
auth:
  type: bearer                  # bearer | api_key_header | api_key_query | basic
  token_env: API_TOKEN
request_delay_ms: 200
timeout_seconds: 10
verify_ssl: true
seed_params_file: ~/.swaggertest/seed_params.json

llm:
  model: gpt-5-mini
  api_key_env: OPENAI_API_KEY
  max_tokens: 4096
  temperature: 0.2
  batch_size: 5
```

**Seed params file (per-user, gitignored, default: `~/.swaggertest/seed_params.json`):**
```json
{
  "id": "42",
  "userId": "abc123",
  "sku": "WIDGET-001"
}
```

---

## 5. Feature Areas

### 5.1 — Spec Discovery & Parsing (GET-based testing)

**Goal:** Given a Swagger UI URL, discover the underlying spec, fetch and parse it, and enumerate all endpoints.

#### Spec Discovery

1. `GET` the Swagger UI HTML page
2. Search HTML/JS for the spec URL using known patterns (`url:` in `SwaggerUIBundle`, `swagger-config` meta tags, common default paths)
3. Resolve relative URLs against the Swagger UI page origin
4. Hard-fail with a clear error if no spec URL is found

#### Parsing

- Supports JSON and YAML (auto-detected)
- Supports OpenAPI 2.0 and 3.x
- Resolves `$ref` via `prance`
- Validates spec via `openapi-spec-validator`
- Extracts per endpoint: method, path, summary, parameters, response codes, request body schema, response 200 schema

#### Local file support

`SpecParser.from_file(path)` loads a spec from disk, skipping Swagger UI discovery. Used by `generate` and `match` commands.

**CLI:**
```bash
swaggertest parse --url https://api.example.com/swagger-ui
```

---

### 5.2 — Execute GET Requests

**Goal:** Fire real HTTP `GET` requests for every `GET` endpoint and record raw results.

- Only `GET` endpoints are called (safe, non-destructive)
- Auth injected per config (Bearer, API key header/query, Basic)
- Path and query params resolved from seed params file
- Missing required params → `skipped_no_param`, not an error
- Configurable timeout, delay, SSL verification

**CLI:**
```bash
swaggertest run --url https://api.example.com/swagger-ui --base-url https://staging.example.com
```

---

### 5.3 — Validate & Report (GET-based)

**Goal:** Validate each response and produce a structured JSON report.

| Condition | Outcome |
|-----------|---------|
| HTTP 200 AND schema valid (or no schema declared) | `passed` |
| HTTP 200 BUT schema invalid | `failed` |
| HTTP status ≠ 200 | `failed` |
| Missing required seed param | `skipped_no_param` |
| Non-GET method | `skipped_non_get` |

Schema validation uses lenient mode: only required fields and types are checked; extra fields are ignored.

**Exit codes:**

| Code | Meaning |
|------|---------|
| `0` | All attempted endpoints passed |
| `1` | One or more endpoints failed |
| `2` | Tool error (spec not found, bad config, network error) |

---

### 5.4 — Rally-Driven LLM Test Generation

**Goal:** Generate structured test cases from Rally ticket exports using OpenAI gpt-5-mini.

#### Data Flow

```
Ticket CSV/Excel → ticket_reader.py → list[dict]
                                    │
Local Spec File → parser.py → list[Endpoint]
                 (from_file)        │
                                    ├→ matcher.py (LLM) → list[TicketMatch]
                                    │
                                    └→ generator.py (LLM) → list[TestCase]
                                                               │
                                          ├→ testcase_io.py → test_cases.json
                                          └→ runner.py (opt) → execution report
```

#### Ticket Reading (`ticket_reader.py`)

- Supports `.csv` and `.xlsx` / `.xls`
- CSV: decoded as UTF-8-BOM (`utf-8-sig`), falls back to `cp1252` with a warning
- Returns raw rows as `list[dict[str, str]]` — no column mapping, no HTML stripping
- First row is treated as the header; every subsequent row becomes a dict of column→value
- The LLM receives all column names and values and identifies the ID and title columns itself

#### Ticket Matching (`matcher.py`)

- Sends compact endpoint catalog (one line per endpoint) + full raw ticket rows to the LLM
- LLM identifies the ID and title columns itself; returns `ticket_id`, `ticket_title`, `matched_endpoints`, `confidence`, `reasoning` per ticket
- Validates returned endpoint strings against the actual spec catalog
- Tickets with no valid matches are warned about and excluded from generation (not silently passed through)
- Default batch size: 5 tickets

#### Test Case Generation (`generator.py`)

- Sends full ticket details + full matched endpoint schemas to the LLM
- LLM generates 3–7 test cases per ticket: happy path, edge cases, negative cases, bug repro (defects)
- Token budget guard: estimates prompt size (`len // 4`); if >80k tokens, truncates endpoint schema descriptions (>300 chars), drops `example` fields, caps `properties` to 20 keys
- Defect tickets always get `priority: "high"`
- Warns if LLM returns <1 or >10 test cases for a ticket
- Default batch size: 3 matches

#### Test Case Execution (`TestCaseRunner`)

- Supports all HTTP methods
- Sends `request_body` as JSON for POST/PUT/PATCH
- Evaluates `TestAssertion` list against actual response
- JSON path evaluator: dot-notation + integer index only (`$.field.nested[0].value`); raises `ValueError` for unsupported syntax (wildcards, filters, recursive descent)

**CLI:**
```bash
# Match only (preview + cost estimate)
swaggertest match --spec openapi.yaml --tickets tickets.csv

# Generate test cases
swaggertest generate --spec openapi.yaml --tickets tickets.csv --output test_cases.json

# Generate and execute
swaggertest generate --spec openapi.yaml --tickets tickets.csv \
  --base-url https://staging.example.com --execute --report results.json
```

---

## 6. Project Structure

```
swaggertest/
├── swaggertest/
│   ├── __init__.py         # Public API + __version__
│   ├── discoverer.py       # Swagger UI scraping & spec URL discovery
│   ├── parser.py           # OpenAPI spec parsing, endpoint extraction, from_file()
│   ├── runner.py           # GET execution (Runner) + test case execution (TestCaseRunner)
│   ├── validator.py        # Response validation (lenient schema mode)
│   ├── reporter.py         # JSON report builder
│   ├── config.py           # Config precedence resolution (AuthConfig, LLMConfig, Config)
│   ├── cli.py              # CLI entrypoint: parse, run, match, generate
│   ├── models.py           # Shared dataclasses: TestCase, TestAssertion, TicketMatch
│   ├── ticket_reader.py    # CSV/Excel → list[dict] raw rows
│   ├── llm_client.py       # OpenAI gpt-5-mini wrapper with usage tracking
│   ├── matcher.py          # LLM-powered ticket→endpoint matching
│   ├── generator.py        # LLM-powered test case generation
│   └── testcase_io.py      # JSON save/load for test cases
├── tests/
├── .swaggertest.yaml
├── .env
├── pyproject.toml
└── README.md
```

---

## 7. Dependencies

| Library | Purpose |
|---------|---------|
| `httpx` | HTTP requests |
| `beautifulsoup4` | Swagger UI HTML scraping |
| `pyyaml` | YAML spec and config parsing |
| `prance` | `$ref` resolution |
| `openapi-spec-validator` | Spec well-formedness validation |
| `jsonschema` | Lenient response body schema validation |
| `typer` | CLI interface |
| `python-dotenv` | `.env` loading |
| `openai` | gpt-5-mini API access |
| `openpyxl` | Excel file parsing |

---
