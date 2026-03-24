# PRD: Swagger API Test Tool
**Version:** 1.0
**Audience:** Internal Dev Team
**Status:** Draft

---

## 1. Overview

A Python tool that accepts a Swagger UI URL, discovers and fetches the underlying OpenAPI spec, enumerates all documented endpoints, fires real HTTP `GET` requests against them, validates responses, and produces a structured JSON report. Usable as both a CLI tool and a Python library.

---

## 2. Goals

- Reduce manual effort of verifying API contracts after changes
- Give the dev team a fast feedback loop on spec-vs-reality drift
- Produce a machine-readable JSON report suitable for CI artifact storage and downstream tooling

---

## 3. Non-Goals (Phases 1–3)

- No test case generation for `POST`, `PUT`, `PATCH`, `DELETE`
- No OAuth2 flow automation
- No HTML or pytest-format reporting
- No test ordering or dependency chaining between endpoints
- No load or performance testing

---

## 4. Users

| User | Context |
|---|---|
| Backend developer | Runs the tool locally against a staging server to verify a new endpoint |
| CI pipeline | Runs the tool on every PR to detect spec drift or broken endpoints |

---

## 5. Configuration & Precedence

All config is resolved in this strict precedence order (highest to lowest):

| Source | Example |
|---|---|
| CLI flag | `--base-url https://staging.example.com` |
| `.env` file | `BASE_URL=https://staging.example.com` |
| `.swaggertest.yaml` | `base_url: https://staging.example.com` |

If `BASE_URL` is absent from all three sources, the tool hard-fails with a clear error — it never falls back to the spec's declared server URL to avoid accidentally hitting production.

**`.env` file (per-user, gitignored):**
```env
BASE_URL=https://staging.example.com
API_TOKEN=your-token-here
```

**`.swaggertest.yaml` (per-project, checked in):**
```yaml
auth:
  type: bearer                  # bearer | api_key_header | api_key_query | basic
  token_env: API_TOKEN          # name of the env var holding the token
request_delay_ms: 200
timeout_seconds: 10
verify_ssl: true
seed_params_file: ~/.swaggertest/seed_params.json   # per-user, gitignored
```

**Seed params file (per-user, gitignored, default: `~/.swaggertest/seed_params.json`):**
```json
{
  "id": "42",
  "userId": "abc123",
  "sku": "WIDGET-001"
}
```
The seed params file location can be overridden via the `seed_params_file` key in `.swaggertest.yaml` or a `--seed-params` CLI flag.

---

## 6. Phases

### Phase 1 — Spec Discovery & Parsing

**Goal:** Given a Swagger UI URL, discover the underlying spec, fetch and parse it, and print a structured summary of all endpoints.

#### Spec Discovery

The tool performs the following steps in order to locate the raw spec:

1. `GET` the Swagger UI HTML page
2. Search the HTML/JS for the spec URL using known patterns:
   - `url: "..."` inside a `SwaggerUIBundle(...)` call
   - `swagger-config` meta tags
   - Common default paths: `/v3/api-docs`, `/v2/api-docs`, `/swagger.json`, `/openapi.json`, `/openapi.yaml`
3. If a relative URL is found, resolve it against the Swagger UI page's origin
4. Fetch the resolved spec URL
5. If no spec URL can be discovered, **hard fail** with:
   ```
   ERROR: Could not locate the OpenAPI spec from the provided Swagger UI URL.
   Tried patterns: [list of attempted paths]
   Please verify the URL or check if the spec endpoint requires authentication.
   ```

#### Parsing

- Support both JSON and YAML spec formats (auto-detected via `Content-Type` or content sniffing)
- Support OpenAPI 2.0 (Swagger) and OpenAPI 3.x
- Resolve internal `$ref` references via `prance`
- Validate spec is well-formed via `openapi-spec-validator`; hard fail with a clear error if not
- Extract per endpoint: HTTP method, path, summary, required parameters, declared response codes

**CLI:**
```bash
swaggertest parse --url https://api.example.com/swagger-ui
```

**Library:**
```python
from swaggertest import SpecParser

spec = SpecParser(url="https://api.example.com/swagger-ui")
endpoints = spec.get_endpoints()
```

**Success Criteria:**
- Spec is correctly discovered from the Swagger UI page in all common patterns
- Failure to discover produces a clear, actionable error message
- Both JSON and YAML specs parse correctly
- All endpoints are extracted with their parameters and declared response codes

---

### Phase 2 — Execute GET Requests

**Goal:** Fire real HTTP `GET` requests for every `GET` endpoint and record raw results.

**Functional Requirements:**

- Only `GET` endpoints are called (safe, non-destructive)
- Base URL resolved via precedence table in §5
- Auth injected per `.swaggertest.yaml` config; supported schemes:
  - Bearer token (`Authorization: Bearer <token>`)
  - API key in header
  - API key in query param
  - Basic auth
- Path parameters resolved from seed params file; if a required path param has no seed value, the endpoint is marked `skipped_no_param` and a warning is logged — no error is raised
- Required query params with no seed value: endpoint marked `skipped_no_param`
- Optional params with no seed value: omitted silently
- Configurable request timeout (default: 10s)
- Configurable delay between requests (default: 0ms)
- Configurable `verify_ssl` (default: `true`); set to `false` for staging servers with self-signed certs

**CLI:**
```bash
swaggertest run --url https://api.example.com/swagger-ui --base-url https://staging.example.com
```

**Library:**
```python
from swaggertest import SpecParser, Runner

spec = SpecParser(url="https://api.example.com/swagger-ui")
runner = Runner(spec, config=".swaggertest.yaml")
results = runner.run()
```

**Success Criteria:**
- All `GET` endpoints with resolvable parameters are called
- Unresolvable endpoints are skipped cleanly with a logged warning
- Auth is correctly injected
- SSL verification, timeouts, and delays behave as configured

---

### Phase 3 — Validate & Report

**Goal:** Validate each response and produce a structured JSON report.

#### Validation Rules

Every called endpoint is evaluated as follows:

| Condition | Outcome |
|---|---|
| HTTP status is `200` AND response schema is valid (or no schema declared) | `passed` |
| HTTP status is `200` BUT response schema is invalid | `failed` |
| HTTP status is not `200` | `failed` |
| Endpoint skipped — missing required seed param | `skipped_no_param` |
| Endpoint skipped — non-GET method | `skipped_non_get` |

**Schema validation** uses lenient mode: only required fields and their types are checked. Extra fields in the response are ignored. If the spec declares no response schema for `200`, schema validation is skipped and the result is `passed` on status code alone.

#### JSON Report Format

```json
{
  "report_version": "1.0",
  "meta": {
    "spec_url": "https://api.example.com/v3/api-docs",
    "swagger_ui_url": "https://api.example.com/swagger-ui",
    "base_url": "https://staging.example.com",
    "run_at": "2025-01-15T10:30:00Z",
    "total_in_spec": 30,
    "total_attempted": 24,
    "passed": 20,
    "failed": 3,
    "skipped_no_param": 1,
    "skipped_non_get": 6
  },
  "results": [
    {
      "method": "GET",
      "path": "/users/{id}",
      "resolved_url": "https://staging.example.com/users/42",
      "status": "passed",
      "http_status_code": 200,
      "response_time_ms": 143,
      "validations": {
        "status_code_ok": true,
        "schema_validated": true,
        "schema_errors": []
      }
    },
    {
      "method": "GET",
      "path": "/orders",
      "resolved_url": "https://staging.example.com/orders",
      "status": "failed",
      "http_status_code": 500,
      "response_time_ms": 312,
      "validations": {
        "status_code_ok": false,
        "schema_validated": null,
        "schema_errors": []
      },
      "errors": ["Expected status 200, got 500"]
    },
    {
      "method": "GET",
      "path": "/products/{sku}",
      "resolved_url": null,
      "status": "skipped_no_param",
      "reason": "Required path parameter 'sku' has no seed value"
    },
    {
      "method": "POST",
      "path": "/users",
      "resolved_url": null,
      "status": "skipped_non_get",
      "reason": "Non-GET methods are not executed in Phase 1–3"
    }
  ]
}
```

**`meta` field definitions:**

| Field | Meaning |
|---|---|
| `total_in_spec` | All endpoints found in the spec |
| `total_attempted` | Endpoints actually called (`total_in_spec` minus all skipped) |
| `passed / failed` | Out of `total_attempted` only |
| `skipped_no_param` | Skipped due to missing seed value |
| `skipped_non_get` | Skipped because method is not GET |

**CLI:**
```bash
swaggertest run --url https://api.example.com/swagger-ui --output report.json
```

**Library:**
```python
results = runner.run()
results.save("report.json")
data = results.to_dict()
```

**Exit codes:**

| Code | Meaning |
|---|---|
| `0` | All attempted endpoints passed |
| `1` | One or more endpoints failed validation |
| `2` | Tool error (spec undiscoverable, config invalid, network error, etc.) |

**Success Criteria:**
- Report is valid JSON matching the schema above
- `meta` counts are always consistent (`passed + failed == total_attempted`)
- Schema validation errors include the offending field path (e.g. `$.user.email: expected string, got null`)
- Exit codes are reliable for CI gating
- `report_version` field enables safe future schema evolution

---

## 7. Project Structure

```
swaggertest/
├── swaggertest/
│   ├── __init__.py
│   ├── discoverer.py   # Phase 1: scrape Swagger UI, find spec URL
│   ├── parser.py       # Phase 1: fetch, parse, extract endpoints
│   ├── runner.py       # Phase 2: execute requests
│   ├── validator.py    # Phase 3: validate responses (lenient schema mode)
│   ├── reporter.py     # Phase 3: build and save JSON report
│   ├── config.py       # Config precedence resolution, env var injection
│   └── cli.py          # CLI entrypoint (typer)
├── tests/
├── .swaggertest.yaml   # Per-project config (checked in)
├── .env                # Per-user secrets (gitignored)
├── pyproject.toml
└── README.md
```

---

## 8. Dependencies

| Library | Purpose |
|---|---|
| `httpx` | HTTP requests |
| `beautifulsoup4` | Swagger UI HTML scraping for spec discovery |
| `pyyaml` | YAML spec and config parsing |
| `prance` | `$ref` resolution |
| `openapi-spec-validator` | Spec well-formedness validation |
| `jsonschema` | Lenient response body schema validation |
| `typer` | CLI interface |
| `python-dotenv` | `.env` loading and env var resolution |

---

## 9. Future Phases (out of scope, noted for awareness)

- **Phase 4:** Mutating methods (`POST`, `PUT`, `DELETE`) with generated payloads
- **Phase 5:** HTML reporting, pytest output, CI badge generation
- **Phase 6:** Test sequencing (create → read → delete flows)
- **Phase 6:** Response time thresholds and SLA warnings