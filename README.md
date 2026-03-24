# SwaggerTest

A Python tool that discovers OpenAPI specs from Swagger UI pages, tests all GET endpoints, and produces structured JSON reports.

## Installation

```bash
# Clone and install
cd Autonomous-QA
python -m venv .venv
source .venv/bin/activate
pip install -e .

# With dev dependencies (for running tests)
pip install -e ".[dev]"
```

## Quick Start

### 1. Parse a Swagger UI page

Discover the spec and list all endpoints:

```bash
swaggertest parse --url https://api.example.com/swagger-ui
```

### 2. Run tests against an API

```bash
swaggertest run \
  --url https://api.example.com/swagger-ui \
  --base-url https://staging.example.com \
  --output report.json
```

## Configuration

Configuration is resolved in strict precedence order: **CLI flags > `.env` file > `.swaggertest.yaml`**.

### `.env` (per-user, gitignored)

```env
BASE_URL=https://staging.example.com
API_TOKEN=your-token-here
```

### `.swaggertest.yaml` (per-project, checked in)

```yaml
auth:
  type: bearer              # bearer | api_key_header | api_key_query | basic
  token_env: API_TOKEN      # env var holding the token
request_delay_ms: 200
timeout_seconds: 10
verify_ssl: true
seed_params_file: ~/.swaggertest/seed_params.json
```

### Seed Parameters

Path and query parameters are resolved from a seed params JSON file. Create `~/.swaggertest/seed_params.json`:

```json
{
  "id": "42",
  "userId": "abc123",
  "sku": "WIDGET-001"
}
```

Endpoints with required parameters that have no seed value are skipped with a warning.

## CLI Reference

### `swaggertest parse`

```
swaggertest parse --url <SWAGGER_UI_URL>
```

Discovers the OpenAPI spec and prints all endpoints with their methods, paths, parameters, and response codes.

### `swaggertest run`

```
swaggertest run --url <SWAGGER_UI_URL> [OPTIONS]
```

| Option | Description | Default |
|---|---|---|
| `--url` | Swagger UI URL (required) | — |
| `--base-url` | Base URL for API requests | from config |
| `--output` | Path to write JSON report | stdout |
| `--seed-params` | Path to seed params JSON file | from config |
| `--config` | Path to config file | `.swaggertest.yaml` |

### Exit Codes

| Code | Meaning |
|---|---|
| `0` | All attempted endpoints passed |
| `1` | One or more endpoints failed |
| `2` | Tool error (spec not found, bad config, etc.) |

## Library Usage

```python
from swaggertest import SpecParser, Runner, Report
from swaggertest.config import load_config
from swaggertest.validator import validate_results

# Phase 1: Discover and parse
spec = SpecParser(url="https://api.example.com/swagger-ui")
endpoints = spec.get_endpoints()

# Phase 2: Execute GET requests
config = load_config(cli_base_url="https://staging.example.com")
runner = Runner(spec, config=config)
results = runner.run()

# Phase 3: Validate and report
validate_results(results)
report = Report(
    results,
    spec_url=spec.spec_url,
    swagger_ui_url=spec.swagger_ui_url,
    base_url=config.base_url,
)
report.save("report.json")
data = report.to_dict()
```

## Running Tests

```bash
pytest tests/ -v
```

## Project Structure

```
swaggertest/
├── swaggertest/
│   ├── __init__.py        # Public API: SpecParser, Runner, Report
│   ├── discoverer.py      # Swagger UI scraping & spec URL discovery
│   ├── parser.py          # OpenAPI spec parsing & endpoint extraction
│   ├── runner.py          # GET request execution
│   ├── validator.py       # Response validation (lenient schema mode)
│   ├── reporter.py        # JSON report builder
│   ├── config.py          # Config precedence resolution
│   └── cli.py             # CLI entrypoint (typer)
├── tests/
├── .swaggertest.yaml      # Per-project config
├── .env                   # Per-user secrets (gitignored)
└── pyproject.toml
```
