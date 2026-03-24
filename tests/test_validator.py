"""Tests for response validation."""

from swaggertest.runner import EndpointResult
from swaggertest.validator import validate_results


def test_passed_with_valid_schema():
    result = EndpointResult(
        method="GET",
        path="/users/{id}",
        resolved_url="https://example.com/users/42",
        http_status_code=200,
        response_time_ms=100,
        response_body={"id": 42, "name": "Alice", "extra": "ignored"},
        response_schema_200={
            "type": "object",
            "required": ["id", "name"],
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
            },
            "additionalProperties": False,
        },
    )
    validate_results([result])
    assert result.status == "passed"
    assert result._validations["schema_validated"] is True


def test_failed_wrong_status_code():
    result = EndpointResult(
        method="GET",
        path="/orders",
        resolved_url="https://example.com/orders",
        http_status_code=500,
        response_time_ms=200,
        response_body=None,
    )
    validate_results([result])
    assert result.status == "failed"
    assert "Expected status 200, got 500" in result.errors


def test_failed_schema_mismatch():
    result = EndpointResult(
        method="GET",
        path="/items",
        resolved_url="https://example.com/items",
        http_status_code=200,
        response_time_ms=50,
        response_body={"id": "not-an-int"},
        response_schema_200={
            "type": "object",
            "required": ["id"],
            "properties": {"id": {"type": "integer"}},
        },
    )
    validate_results([result])
    assert result.status == "failed"
    assert result._validations["schema_validated"] is False


def test_passed_no_schema():
    result = EndpointResult(
        method="GET",
        path="/health",
        resolved_url="https://example.com/health",
        http_status_code=200,
        response_time_ms=10,
        response_body="OK",
    )
    validate_results([result])
    assert result.status == "passed"


def test_skipped_endpoints_untouched():
    r1 = EndpointResult(method="POST", path="/users", status="skipped_non_get", reason="Non-GET")
    r2 = EndpointResult(method="GET", path="/x/{id}", status="skipped_no_param", reason="Missing param")
    validate_results([r1, r2])
    assert r1.status == "skipped_non_get"
    assert r2.status == "skipped_no_param"
