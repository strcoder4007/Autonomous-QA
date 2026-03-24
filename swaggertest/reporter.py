"""Phase 3: Build and save the structured JSON report."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from swaggertest.runner import EndpointResult


class Report:
    """Structured JSON report of test results."""

    def __init__(
        self,
        results: list[EndpointResult],
        *,
        spec_url: str,
        swagger_ui_url: str,
        base_url: str,
    ):
        self._results = results
        self._spec_url = spec_url
        self._swagger_ui_url = swagger_ui_url
        self._base_url = base_url

    def to_dict(self) -> dict[str, Any]:
        total_in_spec = len(self._results)
        skipped_non_get = sum(1 for r in self._results if r.status == "skipped_non_get")
        skipped_no_param = sum(1 for r in self._results if r.status == "skipped_no_param")
        total_attempted = total_in_spec - skipped_non_get - skipped_no_param
        passed = sum(1 for r in self._results if r.status == "passed")
        failed = sum(1 for r in self._results if r.status == "failed")

        return {
            "report_version": "1.0",
            "meta": {
                "spec_url": self._spec_url,
                "swagger_ui_url": self._swagger_ui_url,
                "base_url": self._base_url,
                "run_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "total_in_spec": total_in_spec,
                "total_attempted": total_attempted,
                "passed": passed,
                "failed": failed,
                "skipped_no_param": skipped_no_param,
                "skipped_non_get": skipped_non_get,
            },
            "results": [self._format_result(r) for r in self._results],
        }

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @property
    def has_failures(self) -> bool:
        return any(r.status == "failed" for r in self._results)

    @staticmethod
    def _format_result(r: EndpointResult) -> dict[str, Any]:
        if r.status in ("skipped_non_get", "skipped_no_param"):
            return {
                "method": r.method,
                "path": r.path,
                "resolved_url": None,
                "status": r.status,
                "reason": r.reason,
            }

        validations = getattr(r, "_validations", {
            "status_code_ok": r.http_status_code == 200,
            "schema_validated": None,
            "schema_errors": [],
        })

        entry: dict[str, Any] = {
            "method": r.method,
            "path": r.path,
            "resolved_url": r.resolved_url,
            "status": r.status,
            "http_status_code": r.http_status_code,
            "response_time_ms": r.response_time_ms,
            "validations": validations,
        }
        if r.errors:
            entry["errors"] = r.errors
        return entry
