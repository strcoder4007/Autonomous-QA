"""Shared dataclasses for the LLM test generation pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TestAssertion:
    """A single assertion to evaluate against an HTTP response."""

    type: str  # "status_code" | "json_path" | "header" | "response_time"
    expression: str  # e.g. "$.user.id", "Content-Type", "status_code"
    expected: Any  # e.g. 200, "application/json", None (for exists/not_null)
    comparator: str = "equals"  # "equals"|"contains"|"exists"|"not_null"|"matches_regex"|"less_than"


@dataclass
class TestCase:
    """A generated test case targeting a specific API endpoint."""

    name: str
    description: str
    source_ticket: str  # ticket identifier from the input file (e.g. FormattedID)
    target_endpoints: list[str] = field(default_factory=list)  # e.g. ["PUT /members/{id}/pcp"]
    method: str = "GET"
    path: str = ""
    path_params: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    request_body: dict[str, Any] | None = None
    expected_status_code: int = 200
    assertions: list[TestAssertion] = field(default_factory=list)
    edge_cases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    priority: str = "medium"  # "high"|"medium"|"low"


@dataclass
class TicketMatch:
    """Result of matching a ticket row to API endpoints."""

    ticket_id: str
    ticket_title: str
    matched_endpoints: list[str] = field(default_factory=list)  # e.g. ["GET /members/{id}/claims"]
    confidence: str = "medium"  # "high"|"medium"|"low"
    reasoning: str = ""
