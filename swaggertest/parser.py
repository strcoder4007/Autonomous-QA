"""Phase 1: Fetch, parse, and extract endpoints from an OpenAPI spec."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import prance
import yaml
from openapi_spec_validator import validate

from swaggertest.discoverer import discover_spec_url


@dataclass
class Parameter:
    name: str
    location: str  # path, query, header, cookie
    required: bool
    schema: dict[str, Any] | None = None


@dataclass
class Endpoint:
    method: str
    path: str
    summary: str
    parameters: list[Parameter] = field(default_factory=list)
    response_codes: list[str] = field(default_factory=list)
    response_schema_200: dict[str, Any] | None = None


class SpecParser:
    """Discover, fetch, parse, and enumerate endpoints from a Swagger UI URL."""

    def __init__(self, url: str, *, client: httpx.Client | None = None):
        self._swagger_ui_url = url
        own_client = client is None
        if own_client:
            client = httpx.Client(follow_redirects=True, timeout=15)

        try:
            self.spec_url = discover_spec_url(url, client=client)
            self._raw_spec = self._fetch_spec(client, self.spec_url)
            self._resolved_spec = self._resolve_refs(self.spec_url)
            self._validate()
        finally:
            if own_client:
                client.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_spec(client: httpx.Client, spec_url: str) -> dict[str, Any]:
        resp = client.get(spec_url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        text = resp.text
        if "yaml" in content_type or text.lstrip().startswith(("openapi:", "swagger:", "---")):
            return yaml.safe_load(text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return yaml.safe_load(text)

    @staticmethod
    def _resolve_refs(spec_url: str) -> dict[str, Any]:
        parser = prance.ResolvingParser(spec_url, lazy=True, strict=False)
        parser.parse()
        return parser.specification

    def _validate(self) -> None:
        try:
            validate(self._resolved_spec)
        except Exception as exc:
            raise RuntimeError(f"OpenAPI spec validation failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_endpoints(self) -> list[Endpoint]:
        spec = self._resolved_spec
        endpoints: list[Endpoint] = []

        paths = spec.get("paths", {})
        for path, path_item in paths.items():
            # Path-level parameters apply to all methods.
            path_params = _extract_params(path_item.get("parameters", []))

            for method in ("get", "post", "put", "patch", "delete", "head", "options"):
                operation = path_item.get(method)
                if operation is None:
                    continue

                op_params = _extract_params(operation.get("parameters", []))
                # Merge: operation-level overrides path-level by name+location.
                merged = {(p.name, p.location): p for p in path_params}
                merged.update({(p.name, p.location): p for p in op_params})

                response_codes = list((operation.get("responses") or {}).keys())
                response_schema_200 = _extract_200_schema(operation, spec)

                endpoints.append(
                    Endpoint(
                        method=method.upper(),
                        path=path,
                        summary=operation.get("summary", ""),
                        parameters=list(merged.values()),
                        response_codes=response_codes,
                        response_schema_200=response_schema_200,
                    )
                )

        return endpoints

    @property
    def swagger_ui_url(self) -> str:
        return self._swagger_ui_url


def _extract_params(raw: list[dict[str, Any]]) -> list[Parameter]:
    params: list[Parameter] = []
    for p in raw:
        params.append(
            Parameter(
                name=p.get("name", ""),
                location=p.get("in", ""),
                required=p.get("required", False),
                schema=p.get("schema"),
            )
        )
    return params


def _extract_200_schema(operation: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any] | None:
    responses = operation.get("responses", {})
    resp_200 = responses.get("200") or responses.get(200)
    if not resp_200:
        return None

    # OpenAPI 3.x
    content = resp_200.get("content", {})
    json_media = content.get("application/json", {})
    schema = json_media.get("schema")
    if schema:
        return schema

    # OpenAPI 2.x (Swagger)
    return resp_200.get("schema")
