# Handoff Document — SwaggerTest

## Project Summary

SwaggerTest is a Python CLI tool and library that accepts a Swagger UI URL, discovers the underlying OpenAPI spec, fires GET requests against all documented endpoints, validates responses, and produces a structured JSON report. Built for CI pipelines and local developer use.

---

## Architecture

The tool follows a three-phase pipeline:

```
Swagger UI URL → [Phase 1: Discover & Parse] → [Phase 2: Execute GETs] → [Phase 3: Validate & Report] → JSON Report
```

### Phase 1 — Discovery & Parsing (`discoverer.py`, `parser.py`)

- Fetches Swagger UI HTML and extracts the spec URL via four strategies:
  1. `SwaggerUIBundle({ url: "..." })` regex in JS
  2. `<meta name="swagger-config">` tag
  3. `configUrl` in JS → fetch config JSON → extract `url`
  4. Probe well-known paths (`/v3/api-docs`, `/swagger.json`, etc.)
- Fetches the raw spec (JSON or YAML, auto-detected)
- Resolves `$ref` references via `prance`
- Validates spec well-formedness via `openapi-spec-validator`
- Extracts all endpoints with method, path, parameters, response schemas

### Phase 2 — Execution (`runner.py`)

- Iterates all endpoints; only executes `GET` methods
- Resolves path and query parameters from a seed params file
- Injects authentication (bearer, API key header/query, basic)
- Records status code, response body, and timing for each endpoint
- Skips endpoints with missing required params (`skipped_no_param`)

### Phase 3 — Validation & Reporting (`validator.py`, `reporter.py`)

- Checks HTTP status is 200
- Validates response body against declared schema in **lenient mode** (only required fields checked, extra fields ignored)
- Produces a JSON report with meta counts and per-endpoint results

---

## Module Responsibilities

| Module | Purpose |
|---|---|
| `discoverer.py` | Scrape Swagger UI HTML to find the spec URL |
| `parser.py` | Fetch, parse, validate spec; extract `Endpoint` objects |
| `runner.py` | Execute GET requests; produce `EndpointResult` objects |
| `validator.py` | Validate status codes and response schemas |
| `reporter.py` | Build and serialize the JSON report |
| `config.py` | Merge config from CLI flags, `.env`, and `.swaggertest.yaml` |
| `cli.py` | Typer CLI with `parse` and `run` commands |

---

## Key Data Structures

- **`Endpoint`** — Parsed from spec: method, path, summary, parameters, response codes, 200 schema
- **`EndpointResult`** — Execution result: resolved URL, status code, response body, timing, errors
- **`Config`** — Merged config: base_url, auth, delay, timeout, SSL, seed params
- **`Report`** — Wraps results list; produces the final JSON dict with meta counts

---

## Configuration Precedence (highest → lowest)

1. **CLI flags** (`--base-url`, `--seed-params`)
2. **`.env` file** (`BASE_URL`, `API_TOKEN`)
3. **`.swaggertest.yaml`** (checked into repo)

`BASE_URL` is required from at least one source — the tool hard-fails without it to prevent accidentally hitting production.

---

## Auth Schemes Supported

| Type | Header/Param |
|---|---|
| `bearer` | `Authorization: Bearer <token>` |
| `api_key_header` | `X-API-Key: <token>` |
| `api_key_query` | `?api_key=<token>` |
| `basic` | `Authorization: Basic <base64(token)>` |

---

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | All attempted endpoints passed |
| `1` | One or more endpoints failed validation |
| `2` | Tool error (spec not found, config invalid, network error) |

---

## Test Suite

15 tests across 4 files, all using `pytest` + `respx` (HTTP mocking):

| File | Tests | What it covers |
|---|---|---|
| `test_discoverer.py` | 3 | Spec URL extraction from HTML, fallback paths, error on failure |
| `test_config.py` | 4 | Config loading, precedence, missing BASE_URL, seed params |
| `test_validator.py` | 5 | Schema pass/fail, status code check, no-schema pass, skipped untouched |
| `test_reporter.py` | 3 | Meta count consistency, file save, `has_failures` property |

---

## Dependencies

| Library | Purpose |
|---|---|
| `httpx` | HTTP client |
| `beautifulsoup4` | HTML parsing for spec discovery |
| `pyyaml` | YAML spec/config parsing |
| `prance` | `$ref` resolution in OpenAPI specs |
| `openapi-spec-validator` | Spec validation |
| `jsonschema` | Lenient response schema validation |
| `typer` | CLI framework |
| `python-dotenv` | `.env` file loading |

---

## Known Limitations / Future Work

- Only `GET` endpoints are tested (Phase 1–3 scope)
- No OAuth2 flow automation
- No HTML/pytest reporting format
- No test ordering or dependency chaining
- Future phases (per PRD): mutating methods, HTML reports, test sequencing, SLA thresholds
