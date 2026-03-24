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
