# SwaggerTest

A Python tool that does two things:

1. **GET endpoint testing** — discovers OpenAPI specs from Swagger UI pages, tests all GET endpoints, and produces structured JSON reports.
2. **Rally-driven test generation** — reads Rally ticket exports (CSV/Excel), uses OpenAI gpt-5-mini to match tickets to endpoints and generate structured test cases, with optional execution.

## Installation

```bash
cd Autonomous-QA
python -m venv .venv
source .venv/bin/activate
pip install -e .

# With dev dependencies
pip install -e ".[dev]"
```

## Quick Start

### GET endpoint testing

```bash
# Discover spec and list endpoints
swaggertest parse --url https://api.example.com/swagger-ui

# Run tests and save report
swaggertest run \
  --url https://api.example.com/swagger-ui \
  --base-url https://staging.example.com \
  --output report.json
```

### Ticket-driven test generation

```bash
# Preview ticket→endpoint matches (no test cases generated)
swaggertest match --spec openapi.yaml --tickets tickets.csv

# Generate test cases from Rally tickets
swaggertest generate \
  --spec openapi.yaml \
  --tickets tickets.csv \
  --output test_cases.json

# Generate and immediately execute against staging
swaggertest generate \
  --spec openapi.yaml \
  --tickets tickets.csv \
  --base-url https://staging.example.com \
  --execute \
  --report results.json
```

## Configuration

Configuration is resolved in strict precedence order: **CLI flags > `.env` > `.swaggertest.yaml`**.

### `.env` (per-user, gitignored)

```env
BASE_URL=https://staging.example.com
API_TOKEN=your-token-here
OPENAI_API_KEY=sk-...
```

### `.swaggertest.yaml` (per-project, checked in)

```yaml
auth:
  type: bearer              # bearer | api_key_header | api_key_query | basic
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
  batch_size: 5             # tickets per LLM batch
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

Discovers the OpenAPI spec and prints all endpoints with methods, paths, parameters, and response codes.

### `swaggertest run`

```
swaggertest run --url <SWAGGER_UI_URL> [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--url` | Swagger UI URL (required) | — |
| `--base-url` | Base URL for API requests | from config |
| `--output` | Path to write JSON report | stdout |
| `--seed-params` | Path to seed params JSON file | from config |
| `--config` | Path to config file | `.swaggertest.yaml` |

### `swaggertest match`

```
swaggertest match --spec <SPEC_FILE> --tickets <TICKET_FILE> [OPTIONS]
```

Preview-only: shows ticket→endpoint matches and estimated LLM cost. No test cases generated.

| Option | Description | Default |
|--------|-------------|---------|
| `--spec` | Path to local OpenAPI spec (JSON or YAML) (required) | — |
| `--tickets` | Path to ticket CSV/XLSX file (required) | — |
| `--model` | Override LLM model | from config |
| `--config` | Path to config file | `.swaggertest.yaml` |

### `swaggertest generate`

```
swaggertest generate --spec <SPEC_FILE> --tickets <TICKET_FILE> [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--spec` | Path to local OpenAPI spec (required) | — |
| `--tickets` | Path to ticket CSV/XLSX file (required) | — |
| `--base-url` | Base URL (required if `--execute`) | from config |
| `--output` | Output path for test cases JSON | `test_cases.json` |
| `--execute` | Execute tests after generation | off |
| `--report` | Execution report output path | — |
| `--model` | Override LLM model | from config |
| `--batch-size` | Tickets per LLM batch | from config |
| `--config` | Path to config file | `.swaggertest.yaml` |

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | One or more test failures (run / generate --execute) |
| `2` | Tool error (spec not found, bad config, missing required option, etc.) |

## Library Usage

```python
# GET-based spec testing
from swaggertest import SpecParser, Runner, Report
from swaggertest.config import load_config
from swaggertest.validator import validate_results

spec = SpecParser(url="https://api.example.com/swagger-ui")
config = load_config(cli_base_url="https://staging.example.com")
runner = Runner(spec, config=config)
results = runner.run()
validate_results(results)
report = Report(results, spec_url=spec.spec_url, swagger_ui_url=spec.swagger_ui_url, base_url=config.base_url)
report.save("report.json")

# Ticket-driven test generation
from swaggertest.parser import SpecParser
from swaggertest.ticket_reader import read_tickets
from swaggertest.llm_client import LLMClient
from swaggertest.matcher import match_tickets_to_endpoints
from swaggertest.generator import generate_test_cases
from swaggertest.testcase_io import save_test_cases

parser = SpecParser.from_file("openapi.yaml")
endpoints = parser.get_endpoints()
ticket_rows = read_tickets("tickets.csv")

llm = LLMClient(model="gpt-5-mini")
matches = match_tickets_to_endpoints(ticket_rows, endpoints, llm)
test_cases = generate_test_cases(matches, endpoints, llm)
save_test_cases(test_cases, "test_cases.json", rally_source="tickets.csv", spec_source="openapi.yaml", llm_usage=llm.usage)

print(llm.usage_summary())
```

## Test Case Output Format

`test_cases.json` uses an envelope format:

```json
{
  "generated_at": "2025-01-15T10:30:00Z",
  "generator_version": "1.0.0",
  "source": {
    "ticket_file": "tickets.csv",
    "spec_file": "openapi.yaml"
  },
  "llm_usage": {
    "input_tokens": 12400,
    "output_tokens": 3100,
    "estimated_cost_usd": 0.0621
  },
  "test_cases": [
    {
      "name": "Update member PCP — happy path",
      "description": "Verify that a valid PCP update returns 200",
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
        {"type": "status_code", "expression": "status_code", "expected": 200, "comparator": "equals"},
        {"type": "json_path", "expression": "$.pcpId", "expected": "doc-789", "comparator": "equals"}
      ],
      "edge_cases": ["What if pcpId is null?"],
      "tags": ["pcp", "members"],
      "priority": "medium"
    }
  ]
}
```

## Running Tests

```bash
pytest tests/ -v
```

## Project Structure

```
swaggertest/
├── swaggertest/
│   ├── __init__.py         # Public API + __version__
│   ├── discoverer.py       # Swagger UI scraping & spec URL discovery
│   ├── parser.py           # Spec parsing, endpoint extraction, from_file()
│   ├── runner.py           # Runner (GET) + TestCaseRunner (all methods)
│   ├── validator.py        # Response validation (lenient schema mode)
│   ├── reporter.py         # JSON report builder
│   ├── config.py           # Config: AuthConfig, LLMConfig, Config
│   ├── cli.py              # CLI: parse, run, match, generate
│   ├── models.py           # TestCase, TestAssertion, TicketMatch
│   ├── ticket_reader.py    # CSV/Excel → list[dict] raw rows
│   ├── llm_client.py       # OpenAI gpt-5-mini wrapper with token tracking
│   ├── matcher.py          # LLM ticket→endpoint matching
│   ├── generator.py        # LLM test case generation
│   └── testcase_io.py      # JSON save/load for test cases
├── tests/
├── .swaggertest.yaml
├── .env
└── pyproject.toml
```
