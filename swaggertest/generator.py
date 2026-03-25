"""Generate test cases from TicketMatch results via LLM."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from swaggertest.models import TestAssertion, TestCase, TicketMatch

if TYPE_CHECKING:
    from swaggertest.llm_client import LLMClient
    from swaggertest.parser import Endpoint

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a senior QA engineer generating structured API test cases from Rally tickets and OpenAPI endpoint definitions.

For each ticket, generate 3–7 test cases covering: happy path, edge cases, negative cases (invalid input, \
missing auth, boundary values), and for defect tickets specifically a bug reproduction test case.

Return a JSON object with this exact structure:
{
  "test_cases": [
    {
      "name": "string",
      "description": "string",
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
      "priority": "high"
    }
  ]
}

Use realistic but anonymized test data. Priority: "high" for defects and critical paths, \
"medium" for standard happy path, "low" for edge cases.
assertion.type values: "status_code", "json_path", "header", "response_time"
assertion.comparator values: "equals", "contains", "exists", "not_null", "matches_regex", "less_than"\
"""

_MAX_ESTIMATED_TOKENS = 80_000
_MAX_DESCRIPTION_LEN = 300
_MAX_SCHEMA_KEYS = 20


def _truncate_schema(schema: dict[str, Any] | None) -> dict[str, Any] | None:
    if schema is None:
        return None
    result: dict[str, Any] = {}
    for k, v in schema.items():
        if k == "example":
            continue  # drop example fields entirely
        if k == "description" and isinstance(v, str) and len(v) > _MAX_DESCRIPTION_LEN:
            result[k] = v[:_MAX_DESCRIPTION_LEN] + "…"
        elif k == "properties" and isinstance(v, dict):
            keys = list(v.keys())[:_MAX_SCHEMA_KEYS]
            result[k] = {key: v[key] for key in keys}
        else:
            result[k] = v
    return result


def _endpoint_detail(ep: Endpoint) -> str:
    lines = [f"{ep.method} {ep.path}"]
    if ep.summary:
        lines.append(f"  Summary: {ep.summary}")
    for p in ep.parameters:
        lines.append(f"  Param: {p.name} (in {p.location}, required={p.required})")
    if hasattr(ep, "request_body_schema") and ep.request_body_schema:
        lines.append(
            f"  Request body schema:\n{json.dumps(_truncate_schema(ep.request_body_schema), indent=2)}"
        )
    if ep.response_schema_200:
        lines.append(
            f"  Response 200 schema:\n{json.dumps(_truncate_schema(ep.response_schema_200), indent=2)}"
        )
    return "\n".join(lines)


def _build_user_message(match: TicketMatch, endpoint_map: dict[str, Endpoint]) -> str:
    parts = [
        f"Ticket: {match.ticket_id} — {match.ticket_title}",
        f"Confidence: {match.confidence}",
        f"Reasoning: {match.reasoning}",
        "\nMatched endpoints:",
    ]
    for ep_str in match.matched_endpoints:
        ep = endpoint_map.get(ep_str) or endpoint_map.get(ep_str.upper())
        if ep:
            parts.append(_endpoint_detail(ep))
    return "\n".join(parts)


def _parse_test_cases(data: dict, source_ticket: str, is_defect: bool) -> list[TestCase]:
    raw_cases = data.get("test_cases", [])

    if len(raw_cases) < 1:
        log.warning("LLM returned 0 test cases for %s", source_ticket)
    elif len(raw_cases) > 10:
        log.warning(
            "LLM returned %d test cases for %s (>10), accepting all", len(raw_cases), source_ticket
        )

    test_cases: list[TestCase] = []
    for tc in raw_cases:
        assertions = [
            TestAssertion(
                type=a.get("type", "status_code"),
                expression=a.get("expression", ""),
                expected=a.get("expected"),
                comparator=a.get("comparator", "equals"),
            )
            for a in tc.get("assertions", [])
        ]

        priority = tc.get("priority", "medium")
        if is_defect:
            priority = "high"

        test_cases.append(
            TestCase(
                name=tc.get("name", f"Test for {source_ticket}"),
                description=tc.get("description", ""),
                source_ticket=source_ticket,
                target_endpoints=tc.get("target_endpoints", []),
                method=tc.get("method", "GET"),
                path=tc.get("path", ""),
                path_params=tc.get("path_params", {}),
                query_params=tc.get("query_params", {}),
                headers=tc.get("headers", {}),
                request_body=tc.get("request_body"),
                expected_status_code=tc.get("expected_status_code", 200),
                assertions=assertions,
                edge_cases=tc.get("edge_cases", []),
                tags=tc.get("tags", []),
                priority=priority,
            )
        )
    return test_cases


def generate_test_cases(
    matches: list[TicketMatch],
    endpoints: list[Endpoint],
    llm_client: LLMClient,
    batch_size: int = 3,
) -> list[TestCase]:
    """Generate TestCase objects for each TicketMatch using the LLM."""
    endpoint_map = {f"{ep.method} {ep.path}": ep for ep in endpoints}
    all_test_cases: list[TestCase] = []

    for i in range(0, len(matches), batch_size):
        batch = matches[i : i + batch_size]

        for match in batch:
            print(f"  Generating tests for {match.ticket_id}: {match.ticket_title[:60]}")
            is_defect = match.ticket_id.upper().startswith("DE")
            user_msg = _build_user_message(match, endpoint_map)

            estimated_tokens = len(_SYSTEM_PROMPT + "\n" + user_msg) // 4
            if estimated_tokens > _MAX_ESTIMATED_TOKENS:
                log.warning(
                    "Prompt for %s estimated at ~%d tokens (>%d); schema truncation already applied",
                    match.ticket_id,
                    estimated_tokens,
                    _MAX_ESTIMATED_TOKENS,
                )

            try:
                data = llm_client.chat_json(_SYSTEM_PROMPT, user_msg)
            except Exception as exc:
                log.error("LLM call failed for %s: %s", match.ticket_id, exc)
                continue

            test_cases = _parse_test_cases(data, match.ticket_id, is_defect)
            all_test_cases.extend(test_cases)

    return all_test_cases
