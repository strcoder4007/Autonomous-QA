"""Save and load generated test cases as JSON."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from swaggertest import __version__
from swaggertest.models import TestAssertion, TestCase


def save_test_cases(
    test_cases: list[TestCase],
    output_path: str | Path,
    rally_source: str = "",  # kept for backwards compat; represents the ticket file path
    spec_source: str = "",
    llm_usage: Any | None = None,
) -> None:
    """Serialise test cases to a JSON envelope file."""
    usage_dict = None
    if llm_usage is not None:
        usage_dict = {
            "input_tokens": llm_usage.input_tokens,
            "output_tokens": llm_usage.output_tokens,
            "estimated_cost_usd": round(llm_usage.estimated_cost_usd, 4),
        }

    envelope = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator_version": __version__,
        "source": {
            "ticket_file": rally_source,
            "spec_file": spec_source,
        },
        "llm_usage": usage_dict,
        "test_cases": [asdict(tc) for tc in test_cases],
    }

    out = Path(output_path)
    out.write_text(json.dumps(envelope, indent=2), encoding="utf-8")


def load_test_cases(path: str | Path) -> list[TestCase]:
    """Load test cases from a previously saved JSON envelope or bare list."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_cases: list[dict] = data.get("test_cases", data) if isinstance(data, dict) else data

    result: list[TestCase] = []
    for tc in raw_cases:
        assertions = [
            TestAssertion(
                type=a["type"],
                expression=a["expression"],
                expected=a["expected"],
                comparator=a.get("comparator", "equals"),
            )
            for a in tc.get("assertions", [])
        ]
        result.append(
            TestCase(
                name=tc["name"],
                description=tc.get("description", ""),
                source_ticket=tc["source_ticket"],
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
                priority=tc.get("priority", "medium"),
            )
        )
    return result
