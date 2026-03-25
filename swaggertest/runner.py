"""Phase 2: Execute GET requests for every GET endpoint and record raw results."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from swaggertest.config import Config, load_config
from swaggertest.parser import Endpoint, SpecParser


@dataclass
class EndpointResult:
    method: str
    path: str
    resolved_url: str | None = None
    status: str = ""  # passed | failed | skipped_no_param | skipped_non_get
    http_status_code: int | None = None
    response_time_ms: float | None = None
    response_body: Any = None
    response_schema_200: dict[str, Any] | None = None
    reason: str | None = None
    errors: list[str] = field(default_factory=list)


class Runner:
    """Execute GET requests for all GET endpoints discovered by a ``SpecParser``."""

    def __init__(self, spec: SpecParser, *, config: Config | str = ".swaggertest.yaml", **kwargs: Any):
        self.spec = spec
        if isinstance(config, str):
            self.config = load_config(config_path=config, **kwargs)
        else:
            self.config = config
        self.endpoints = spec.get_endpoints()

    def run(self) -> list[EndpointResult]:
        results: list[EndpointResult] = []
        client = httpx.Client(
            timeout=self.config.timeout_seconds,
            verify=self.config.verify_ssl,
            follow_redirects=True,
        )
        try:
            for ep in self.endpoints:
                result = self._execute(client, ep)
                results.append(result)
                if self.config.request_delay_ms > 0:
                    time.sleep(self.config.request_delay_ms / 1000)
        finally:
            client.close()
        return results

    def _execute(self, client: httpx.Client, ep: Endpoint) -> EndpointResult:
        if ep.method != "GET":
            return EndpointResult(
                method=ep.method,
                path=ep.path,
                status="skipped_non_get",
                reason="Non-GET methods are not executed in Phase 1-3",
            )

        # Resolve path parameters.
        resolved_path = ep.path
        path_params = [p for p in ep.parameters if p.location == "path"]
        for p in path_params:
            value = self.config.seed_params.get(p.name)
            if value is None:
                return EndpointResult(
                    method=ep.method,
                    path=ep.path,
                    status="skipped_no_param",
                    reason=f"Required path parameter '{p.name}' has no seed value",
                )
            resolved_path = re.sub(r"\{" + re.escape(p.name) + r"\}", value, resolved_path)

        # Resolve query parameters.
        query: dict[str, str] = {}
        for p in ep.parameters:
            if p.location != "query":
                continue
            value = self.config.seed_params.get(p.name)
            if value is not None:
                query[p.name] = value
            elif p.required:
                return EndpointResult(
                    method=ep.method,
                    path=ep.path,
                    status="skipped_no_param",
                    reason=f"Required query parameter '{p.name}' has no seed value",
                )
            # Optional params without seed are silently omitted.

        url = f"{self.config.base_url}{resolved_path}"
        headers = self._auth_headers()
        auth_params = self._auth_query_params()
        query.update(auth_params)

        try:
            start = time.monotonic()
            resp = client.get(url, params=query or None, headers=headers)
            elapsed_ms = (time.monotonic() - start) * 1000

            body = None
            try:
                body = resp.json()
            except Exception:
                body = resp.text

            return EndpointResult(
                method=ep.method,
                path=ep.path,
                resolved_url=str(resp.url),
                status="",  # validator will set this
                http_status_code=resp.status_code,
                response_time_ms=round(elapsed_ms, 1),
                response_body=body,
                response_schema_200=ep.response_schema_200,
            )
        except httpx.HTTPError as exc:
            return EndpointResult(
                method=ep.method,
                path=ep.path,
                resolved_url=url,
                status="failed",
                errors=[str(exc)],
            )

    def _auth_headers(self) -> dict[str, str]:
        auth = self.config.auth
        if not auth.token:
            return {}
        if auth.type == "bearer":
            return {"Authorization": f"Bearer {auth.token}"}
        if auth.type == "api_key_header":
            return {"X-API-Key": auth.token}
        if auth.type == "basic":
            import base64
            encoded = base64.b64encode(auth.token.encode()).decode()
            return {"Authorization": f"Basic {encoded}"}
        return {}

    def _auth_query_params(self) -> dict[str, str]:
        auth = self.config.auth
        if auth.type == "api_key_query" and auth.token:
            return {"api_key": auth.token}
        return {}


# ---------------------------------------------------------------------------
# TestCaseRunner — executes LLM-generated TestCase objects
# ---------------------------------------------------------------------------


@dataclass
class TestCaseResult:
    test_case_name: str
    source_ticket: str
    method: str
    path: str
    resolved_url: str | None = None
    status: str = ""  # "passed" | "failed" | "error"
    http_status_code: int | None = None
    response_time_ms: float | None = None
    response_body: Any = None
    assertion_results: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _json_path_get(body: Any, expression: str) -> Any:
    """Evaluate a dot-notation + integer-index JSON path against body.

    Supports: $.field.nested[0].value
    Does NOT support wildcards, filters, or recursive descent.
    Raises ValueError for unsupported syntax.
    """
    import re

    if not expression.startswith("$"):
        raise ValueError(f"JSON path must start with '$', got: {expression!r}")

    remaining = expression[1:].lstrip(".")
    parts: list[str | int] = []

    while remaining:
        bracket_match = re.match(r"^\[(\d+)\](.*)", remaining)
        if bracket_match:
            parts.append(int(bracket_match.group(1)))
            remaining = bracket_match.group(2).lstrip(".")
            continue

        if remaining.startswith("["):
            raise ValueError(
                f"Unsupported JSON path syntax in {expression!r}: only integer indices supported"
            )

        segment = re.split(r"[.\[]", remaining)[0]
        if "*" in segment or "?" in segment:
            raise ValueError(
                f"Unsupported JSON path syntax in {expression!r}: wildcards not supported"
            )

        parts.append(segment)
        remaining = remaining[len(segment):].lstrip(".")

    current = body
    for part in parts:
        if part == "":
            continue
        try:
            current = current[part] if isinstance(current, dict) else current[part]
        except (KeyError, IndexError, TypeError):
            return None

    return current


class TestCaseRunner:
    """Execute LLM-generated TestCase objects against a live API and evaluate assertions."""

    def __init__(self, config: Config) -> None:
        self.config = config

    def run(self, test_cases: list) -> list[TestCaseResult]:
        from swaggertest.models import TestCase  # avoid circular at module level

        results: list[TestCaseResult] = []
        client = httpx.Client(
            timeout=self.config.timeout_seconds,
            verify=self.config.verify_ssl,
            follow_redirects=True,
        )
        try:
            for tc in test_cases:
                result = self._execute_one(client, tc)
                results.append(result)
                if self.config.request_delay_ms > 0:
                    time.sleep(self.config.request_delay_ms / 1000)
        finally:
            client.close()
        return results

    def _resolve_url(self, tc: Any) -> str:
        resolved_path = tc.path
        for key, value in tc.path_params.items():
            resolved_path = resolved_path.replace(f"{{{key}}}", value)
        return f"{self.config.base_url}{resolved_path}"

    def _auth_headers(self) -> dict[str, str]:
        auth = self.config.auth
        if not auth.token:
            return {}
        if auth.type == "bearer":
            return {"Authorization": f"Bearer {auth.token}"}
        if auth.type == "api_key_header":
            return {"X-API-Key": auth.token}
        if auth.type == "basic":
            import base64
            encoded = base64.b64encode(auth.token.encode()).decode()
            return {"Authorization": f"Basic {encoded}"}
        return {}

    def _evaluate_assertions(
        self,
        tc: Any,
        status_code: int,
        body: Any,
        headers: dict[str, str],
        elapsed_ms: float,
    ) -> list[dict]:
        import re

        results: list[dict] = []
        for assertion in tc.assertions:
            passed = False
            actual: Any = None
            error: str | None = None

            try:
                if assertion.type == "status_code":
                    actual = status_code
                elif assertion.type == "json_path":
                    actual = _json_path_get(body, assertion.expression)
                elif assertion.type == "header":
                    actual = headers.get(assertion.expression) or headers.get(
                        assertion.expression.lower()
                    )
                elif assertion.type == "response_time":
                    actual = elapsed_ms
                else:
                    error = f"Unknown assertion type: {assertion.type!r}"

                if error is None:
                    cmp = assertion.comparator
                    if cmp == "equals":
                        passed = actual == assertion.expected
                    elif cmp == "contains":
                        passed = assertion.expected in str(actual) if actual is not None else False
                    elif cmp in ("exists", "not_null"):
                        passed = actual is not None
                    elif cmp == "matches_regex":
                        passed = (
                            bool(re.search(str(assertion.expected), str(actual)))
                            if actual is not None
                            else False
                        )
                    elif cmp == "less_than":
                        passed = float(actual) < float(assertion.expected) if actual is not None else False
                    else:
                        error = f"Unknown comparator: {cmp!r}"

            except ValueError as exc:
                error = str(exc)

            results.append(
                {
                    "type": assertion.type,
                    "expression": assertion.expression,
                    "expected": assertion.expected,
                    "comparator": assertion.comparator,
                    "actual": actual,
                    "passed": passed,
                    "error": error,
                }
            )
        return results

    def _execute_one(self, client: httpx.Client, tc: Any) -> TestCaseResult:
        url = self._resolve_url(tc)
        headers = {**self._auth_headers(), **tc.headers}

        auth_params: dict[str, str] = {}
        if self.config.auth.type == "api_key_query" and self.config.auth.token:
            auth_params["api_key"] = self.config.auth.token
        query = {**tc.query_params, **auth_params}

        try:
            kwargs: dict[str, Any] = {
                "method": tc.method,
                "url": url,
                "headers": headers,
                "params": query or None,
            }
            if tc.method.upper() in ("POST", "PUT", "PATCH") and tc.request_body is not None:
                kwargs["json"] = tc.request_body

            start = time.monotonic()
            resp = client.request(**kwargs)
            elapsed_ms = round((time.monotonic() - start) * 1000, 1)

            body: Any = None
            try:
                body = resp.json()
            except Exception:
                body = resp.text

            resp_headers = dict(resp.headers)
            assertion_results = self._evaluate_assertions(
                tc, resp.status_code, body, resp_headers, elapsed_ms
            )
            all_passed = all(r["passed"] for r in assertion_results if r["error"] is None)

            return TestCaseResult(
                test_case_name=tc.name,
                source_ticket=tc.source_ticket,
                method=tc.method,
                path=tc.path,
                resolved_url=str(resp.url),
                status="passed" if all_passed else "failed",
                http_status_code=resp.status_code,
                response_time_ms=elapsed_ms,
                response_body=body,
                assertion_results=assertion_results,
            )

        except httpx.HTTPError as exc:
            return TestCaseResult(
                test_case_name=tc.name,
                source_ticket=tc.source_ticket,
                method=tc.method,
                path=tc.path,
                resolved_url=url,
                status="error",
                errors=[str(exc)],
            )
