# Test Case Generation from Rally Tickets + Swagger API Docs

Autonomous Test Case Generation

What We're Building

A tool that automatically writes test plans for our APIs by reading two inputs:

1. Rally tickets — the user stories and bug reports our team already writes
2. API documentation — the Swagger/OpenAPI specs that describe how our APIs work

---

How It Works (3 Steps)

Step 1: Read & Understand

- The tool reads our exported Rally file (CSV, JSON, or XML — whatever Rally gives us)
- It also reads our API documentation from a Swagger URL
- It pulls out the key info: what does this ticket ask for? What API endpoints exist?

Step 2: Connect the Dots — Matching Tickets to API Endpoints

This is where the tool figures out which API endpoints need to be tested for each Rally ticket. Without this step, you'd have a pile of tickets and a pile of endpoints with no connection between them.

How Matching Works

The tool uses a two-pass approach:

Pass 1 — Smart Keyword Matching (instant, free)

The tool looks at the words in your ticket and compares them to the words in each API endpoint's path, name, and description.

▎ Example:

▎ Rally ticket US1042: "As a member, I want to view my claims history so I can track my medical expenses"

▎ The tool scans all your API endpoints and finds:  
 ▎ - GET /members/{id}/claims — strong match (shares "member" and "claims")
▎ - GET /claims/{claimId}/details — moderate match (shares "claims")  
 ▎ - GET /providers/search — no match

▎ Both matching endpoints get linked to this ticket.

This works well for straightforward tickets where the business language lines up with the API naming.

Pass 2 — AI-Assisted Matching (optional, for tricky cases)

Sometimes the ticket uses business language that doesn't appear anywhere in the API. Keyword matching fails here, so the AI steps in.

▎ Example:

▎ Rally defect DE3871: "Member receives an error when trying to update their primary care physician"

▎ The API has no endpoint with "physician" or "primary care" in the name. Keyword matching returns nothing.

▎ The AI reads the ticket, understands the intent, and identifies:  
 ▎ - PUT /members/{id}/pcp — this is the endpoint ("pcp" = primary care physician)
▎ - GET /providers/{npi} — likely needed too, since updating a PCP requires looking up the new provider

▎ A human might take 5-10 minutes to make this connection. The AI does it in seconds.

Another Example — One Ticket, Multiple Endpoints

▎ Rally ticket US2205: "As an admin, I want to deactivate a user account and notify them via email"

▎ This ticket involves two actions, so the tool matches it to multiple endpoints:  
 ▎ - PATCH /users/{id}/status — for deactivating the account
▎ - POST /notifications/email — for sending the notification

▎ Both endpoints get linked, and test cases will be generated for the full workflow.

What the Output Looks Like

After matching, you can preview the results before moving to test generation:

┌───────────────────────────────────┬─────────────────────────────────────────────────────────┬──────────────┐  
 │ Rally Ticket │ Matched API Endpoints │ Match Method │
├───────────────────────────────────┼─────────────────────────────────────────────────────────┼──────────────┤  
 │ US1042 — View claims history │ GET /members/{id}/claims, GET /claims/{claimId}/details │ Keyword │
├───────────────────────────────────┼─────────────────────────────────────────────────────────┼──────────────┤
│ DE3871 — PCP update error │ PUT /members/{id}/pcp, GET /providers/{npi} │ AI-assisted │  
 ├───────────────────────────────────┼─────────────────────────────────────────────────────────┼──────────────┤  
 │ US2205 — Deactivate user + notify │ PATCH /users/{id}/status, POST /notifications/email │ AI-assisted │  
 ├───────────────────────────────────┼─────────────────────────────────────────────────────────┼──────────────┤  
 │ US0988 — Check eligibility │ GET /members/{id}/eligibility │ Keyword │
└───────────────────────────────────┴─────────────────────────────────────────────────────────┴──────────────┘

Step 3: Generate Test Cases

- For each ticket + its matched endpoints, the AI generates test cases covering:
  - Happy path — does it work as expected?
  - Edge cases — what about empty inputs, missing data, invalid IDs?
  - Bug reproduction — for defect tickets, a test that would catch the reported bug
- Output is a structured file (JSON or YAML) listing every test case with clear expected outcomes

---

What We Get

A reviewable test plan JSON file where each test case includes:

- A human-readable name and description
- Which Rally ticket it came from
- Which API endpoint it targets
- What inputs to send
- What the expected response should be
- Suggested edge cases to also consider

---

Cost & Time Controls

- Dry-run mode — preview which tickets match which endpoints before spending any AI credits
- Batching — tickets are grouped smartly to minimize AI API calls
- Cost summary — after each run, we see exactly how many AI tokens were used and the estimated cost

---

What It Doesn't Do (Yet)

- It doesn't run the tests — it generates the plan. Running comes later.
- It doesn't modify anything in Rally
- It doesn't require any coding knowledge to review the output

---

The Workflow for our Team

1. Export tickets from Rally (CSV is easiest)
2. Run one command pointing to the Rally file and our Swagger URL
3. Review the generated test cases — edit or approve
4. (Future) Feed approved test cases into the test runner for automated execution

# Technical Details

The swaggertest tool already discovers OpenAPI specs, executes GET requests, and validates responses. This plan adds a new capability: **LLM-powered test case generation** that reads exported Rally tickets (user stories + defects), matches them to relevant API endpoints from the spec, and uses Claude to generate structured test case definitions (JSON/YAML).

The goal is to bridge the gap between business requirements (Rally) and API test coverage — automatically producing reviewable, structured test plans that can later be executed.

---

## New Modules

| Module                       | Purpose                                                                                 |
| ---------------------------- | --------------------------------------------------------------------------------------- |
| `swaggertest/models.py`      | Shared dataclasses: `RallyTicket`, `TestCase`, `TestAssertion`                          |
| `swaggertest/rally.py`       | Parse Rally exports (CSV, JSON, XML) → `RallyTicket` list                               |
| `swaggertest/matcher.py`     | Match tickets → relevant `Endpoint` objects (keyword heuristic + optional LLM fallback) |
| `swaggertest/llm_client.py`  | Thin wrapper around `anthropic` SDK with retries, token tracking, cost reporting        |
| `swaggertest/generator.py`   | Orchestrate: build prompts, call Claude, parse JSON → `TestCase` objects                |
| `swaggertest/testcase_io.py` | Save/load test cases as JSON or YAML                                                    |

Modify existing: `config.py` (add `LLMConfig`), `cli.py` (add `generate` + `match` commands), `pyproject.toml` (add `anthropic` dep).

---

## Data Models (`models.py`)

**RallyTicket**: id, ticket_type ("user_story"|"defect"), title, description, acceptance_criteria, repro_steps, expected_behavior, tags, raw dict.

**TestCase**: name, description, source_ticket (Rally ID), target_endpoints (e.g. `["GET /users/{id}"]`), method, path, path_params, query_params, headers, request_body, expected_status_code, assertions list, edge_cases (prose list), tags, priority.

**TestAssertion**: type ("status_code"|"json_path"|"header"|"response_time"), expression, expected value, comparator ("equals"|"contains"|"exists"|"not_null"|"matches_regex").

---

## Rally Parsing (`rally.py`)

Single entry point: `parse_rally_export(path) -> list[RallyTicket]`

- Detect format by file extension
- **CSV**: `csv.DictReader`, map common Rally headers (FormattedID, Name, Description, AcceptanceCriteria, c_ReproSteps)
- **JSON**: Handle both `{"QueryResult": {"Results": [...]}}` and flat arrays
- **XML**: `xml.etree.ElementTree`, Rally wraps items in `<Results>`
- Strip HTML tags from rich text fields (stdlib `html.parser`, no new dep)
- Warn on tickets missing key fields, don't fail

---

## Endpoint Matching (`matcher.py`)

Two-phase approach to control LLM costs:

1. **Keyword heuristic** (free, fast): Tokenize ticket text, score against endpoint path segments + summary + param names. Jaccard similarity with configurable threshold (default 0.3).
2. **LLM fallback** (opt-in via `--llm-match`): Send compact endpoint list (method + path + summary only) to Claude for ambiguous matches.

Returns: `dict[ticket_id, list[Endpoint]]`

---

## LLM Client (`llm_client.py`)

- Wraps `anthropic` Python SDK
- API key from `ANTHROPIC_API_KEY` env var (consistent with existing config pattern)
- Default model: `claude-sonnet-4-20250514` (configurable)
- Built-in SDK retry for 429/529 errors
- Tracks cumulative input/output tokens and estimated cost
- JSON response parsing with one retry on malformed output

---

## Test Case Generator (`generator.py`)

`generate_test_cases(tickets, endpoints, llm_client, ...) -> list[TestCase]`

**Prompt strategy:**

- System prompt: QA engineer role, JSON schema for output, rules (1-5 tests per ticket, happy + negative paths, defects → repro tests, stories → AC coverage)
- User message per batch: ticket details + matched endpoint specs (path, params, response schema top-level only)
- Batch tickets sharing endpoints together (default batch_size=5) to amortize context

**Post-processing:** Validate endpoints exist in spec, deduplicate similar test cases, assign deterministic names if vague.

---

## Test Case I/O (`testcase_io.py`)

Output wraps test cases with metadata:

```json
{
  "generated_at": "ISO-8601",
  "generator_version": "1.0",
  "source": {"rally_export": "file.csv", "spec_url": "..."},
  "test_cases": [...]
}
```

---

## CLI Commands (additions to `cli.py`)

**`swaggertest generate`** — Main workflow:

- `--url` (required): Swagger UI URL
- `--rally` (required): Path to Rally export file
- `--output` (default: `test_cases.json`): Output path
- `--format` (default: json): json or yaml
- `--llm-match`: Use LLM for endpoint matching
- `--model`: Override Claude model
- `--batch-size`: Tickets per LLM call (default 5)
- `--dry-run`: Show ticket→endpoint matches without calling LLM

**`swaggertest match`** — Preview matching only (no LLM generation cost):

- `--url`, `--rally`, `--llm-match`

---

## Config Changes (`config.py`)

Add `LLMConfig` dataclass, loaded from `.swaggertest.yaml` under `llm:` key:

```yaml
llm:
  model: claude-sonnet-4-20250514
  api_key_env: ANTHROPIC_API_KEY
  max_tokens: 4096
  batch_size: 5
```

---

## Implementation Order

1. `models.py` — no dependencies
2. `rally.py` + `testcase_io.py` — depend only on models (parallel)
3. `matcher.py` + `llm_client.py` — depend on models + existing parser (parallel)
4. `generator.py` — depends on all above
5. `config.py` changes + `cli.py` commands
6. `pyproject.toml` — add `anthropic>=0.40`

---

## Key Files to Modify

- `swaggertest/parser.py` — reuse `Endpoint`, `Parameter` dataclasses
- `swaggertest/config.py` — extend with `LLMConfig`
- `swaggertest/cli.py` — add `generate` and `match` commands (follow existing `parse_cmd`/`run_cmd` patterns)
- `swaggertest/__init__.py` — export new public classes
- `pyproject.toml` — add anthropic dependency

---

## Verification Plan

1. **Unit tests** (mock LLM calls):
   - `test_rally.py`: CSV/JSON/XML parsing, HTML stripping, missing fields
   - `test_matcher.py`: keyword scoring, no-match → empty, LLM fallback mock
   - `test_generator.py`: prompt construction, JSON parsing, batch splitting, malformed JSON retry
   - `test_llm_client.py`: token tracking, missing API key error, retry behavior
   - `test_testcase_io.py`: JSON/YAML round-trip save/load
   - `test_models.py`: serialization, optional field defaults

2. **Integration test**: End-to-end `generate` command with a sample Rally CSV + a mocked Swagger UI → verify output JSON contains valid test cases

3. **Manual verification**: Run against a real Swagger UI + real Rally export, review generated test cases for quality
