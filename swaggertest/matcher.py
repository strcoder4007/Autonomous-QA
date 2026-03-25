"""Match ticket rows to API endpoints via LLM."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from swaggertest.models import TicketMatch

if TYPE_CHECKING:
    from swaggertest.llm_client import LLMClient
    from swaggertest.parser import Endpoint

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an experienced QA engineer. Your task is to match tickets (user stories and defects) \
to the API endpoints they are most likely testing.

Return your answer as a JSON object with the following structure:
{
  "matches": [
    {
      "ticket_id": "<the ticket's ID value>",
      "ticket_title": "<the ticket's title or name>",
      "matched_endpoints": ["GET /members/{id}", "PUT /members/{id}/pcp"],
      "confidence": "high",
      "reasoning": "The ticket describes updating a member's PCP..."
    }
  ]
}

Confidence levels: "high" (clearly related), "medium" (probably related), "low" (possibly related).
If a ticket has no matching endpoints, set matched_endpoints to an empty array.
Only include endpoints from the provided catalog. Use the exact METHOD /path format shown.
For ticket_id, use the value of whichever column looks like an ID (e.g. FormattedID, ID, Key).
For ticket_title, use the value of whichever column looks like a name or summary.\
"""


def _build_endpoint_catalog(endpoints: list[Endpoint]) -> str:
    lines: list[str] = []
    for ep in endpoints:
        summary = f" — {ep.summary}" if ep.summary else ""
        lines.append(f"{ep.method} {ep.path}{summary}")
    return "\n".join(lines)


def _build_ticket_block(tickets: list[dict[str, str]]) -> str:
    parts: list[str] = []
    for i, row in enumerate(tickets, start=1):
        lines = [f"[Ticket {i}]"]
        for key, value in row.items():
            val = str(value).strip()
            if val:
                lines.append(f"  {key}: {val[:500]}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _find_row(batch: list[dict[str, str]], ticket_id: str) -> dict[str, str] | None:
    """Find a row in the batch whose any column value matches ticket_id."""
    for row in batch:
        if ticket_id in row.values():
            return row
    return None


def match_tickets_to_endpoints(
    tickets: list[dict[str, str]],
    endpoints: list[Endpoint],
    llm_client: LLMClient,
    batch_size: int = 5,
) -> list[TicketMatch]:
    """Match each ticket row to relevant API endpoints using the LLM."""
    endpoint_map = {f"{ep.method} {ep.path}": ep for ep in endpoints}
    catalog = _build_endpoint_catalog(endpoints)
    results: list[TicketMatch] = []

    for i in range(0, len(tickets), batch_size):
        batch = tickets[i : i + batch_size]
        print(f"  Matching tickets {i + 1}–{min(i + batch_size, len(tickets))}")

        user_msg = (
            f"Endpoint catalog:\n{catalog}\n\n"
            f"Tickets to match:\n{_build_ticket_block(batch)}"
        )

        try:
            data = llm_client.chat_json(_SYSTEM_PROMPT, user_msg)
        except Exception as exc:
            log.error("LLM call failed for batch %d–%d: %s", i + 1, i + batch_size, exc)
            continue

        for match in data.get("matches", []):
            ticket_id = str(match.get("ticket_id", "")).strip()
            ticket_title = str(match.get("ticket_title", "")).strip()
            matched_strs: list[str] = match.get("matched_endpoints", [])
            confidence = match.get("confidence", "medium")
            reasoning = match.get("reasoning", "")

            if not ticket_id:
                log.warning("LLM returned a match with no ticket_id, skipping")
                continue

            # Validate endpoint strings against the actual spec catalog
            valid_endpoints: list[str] = []
            for ep_str in matched_strs:
                if ep_str in endpoint_map or ep_str.upper() in endpoint_map:
                    valid_endpoints.append(ep_str)
                else:
                    log.warning(
                        "LLM returned unknown endpoint '%s' for %s, ignoring", ep_str, ticket_id
                    )

            if not valid_endpoints:
                log.warning(
                    "No valid endpoints matched for %s — excluding from generation", ticket_id
                )
                continue

            results.append(
                TicketMatch(
                    ticket_id=ticket_id,
                    ticket_title=ticket_title,
                    matched_endpoints=valid_endpoints,
                    confidence=confidence,
                    reasoning=reasoning,
                )
            )

    return results
