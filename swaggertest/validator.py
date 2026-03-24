"""Phase 3: Validate responses — status code and lenient schema checking."""

from __future__ import annotations

from typing import Any

import jsonschema

from swaggertest.runner import EndpointResult


def validate_results(results: list[EndpointResult]) -> list[EndpointResult]:
    """Validate each endpoint result in-place and return the list."""
    for r in results:
        if r.status in ("skipped_non_get", "skipped_no_param"):
            continue
        if r.status == "failed":
            # Already failed (e.g. network error).
            continue
        _validate_one(r)
    return results


def _validate_one(result: EndpointResult) -> None:
    errors: list[str] = []

    # Check status code.
    status_code_ok = result.http_status_code == 200
    if not status_code_ok:
        errors.append(f"Expected status 200, got {result.http_status_code}")

    # Schema validation (lenient mode).
    schema_validated: bool | None = None
    schema_errors: list[str] = []

    if status_code_ok and result.response_schema_200:
        schema_validated, schema_errors = _lenient_schema_check(
            result.response_body, result.response_schema_200
        )
        if not schema_validated:
            errors.extend(schema_errors)
    elif status_code_ok:
        # No schema declared — pass on status code alone.
        schema_validated = True

    result.errors = errors
    result.status = "passed" if not errors else "failed"

    # Attach validation details for the reporter.
    result._validations = {  # type: ignore[attr-defined]
        "status_code_ok": status_code_ok,
        "schema_validated": schema_validated,
        "schema_errors": schema_errors,
    }


def _lenient_schema_check(body: Any, schema: dict[str, Any]) -> tuple[bool, list[str]]:
    """Check only required fields and their types. Extra fields are ignored."""
    lenient = _make_lenient(schema)
    validator = jsonschema.Draft202012Validator(lenient)
    errs = list(validator.iter_errors(body))
    if not errs:
        return True, []
    messages = [f"$.{'.'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in errs]
    return False, messages


def _make_lenient(schema: dict[str, Any]) -> dict[str, Any]:
    """Strip ``additionalProperties: false`` so extra fields are allowed."""
    if not isinstance(schema, dict):
        return schema
    out = {}
    for k, v in schema.items():
        if k == "additionalProperties" and v is False:
            continue
        elif k == "properties" and isinstance(v, dict):
            out[k] = {pk: _make_lenient(pv) for pk, pv in v.items()}
        elif k == "items" and isinstance(v, dict):
            out[k] = _make_lenient(v)
        elif isinstance(v, dict):
            out[k] = _make_lenient(v)
        else:
            out[k] = v
    return out
