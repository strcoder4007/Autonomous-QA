"""Tests for the JSON report builder."""

from swaggertest.reporter import Report
from swaggertest.runner import EndpointResult
from swaggertest.validator import validate_results


def test_report_meta_counts():
    results = [
        EndpointResult(method="GET", path="/a", resolved_url="u", http_status_code=200, response_time_ms=10),
        EndpointResult(method="GET", path="/b", resolved_url="u", http_status_code=500, response_time_ms=10),
        EndpointResult(method="GET", path="/c/{id}", status="skipped_no_param", reason="no id"),
        EndpointResult(method="POST", path="/d", status="skipped_non_get", reason="non-GET"),
    ]
    validate_results(results)

    report = Report(results, spec_url="s", swagger_ui_url="u", base_url="b")
    d = report.to_dict()

    assert d["report_version"] == "1.0"
    meta = d["meta"]
    assert meta["total_in_spec"] == 4
    assert meta["total_attempted"] == 2
    assert meta["passed"] == 1
    assert meta["failed"] == 1
    assert meta["skipped_no_param"] == 1
    assert meta["skipped_non_get"] == 1
    assert meta["passed"] + meta["failed"] == meta["total_attempted"]


def test_report_save(tmp_path):
    results = [
        EndpointResult(method="GET", path="/x", resolved_url="u", http_status_code=200, response_time_ms=5),
    ]
    validate_results(results)
    report = Report(results, spec_url="s", swagger_ui_url="u", base_url="b")
    path = str(tmp_path / "report.json")
    report.save(path)

    import json
    with open(path) as f:
        data = json.load(f)
    assert data["report_version"] == "1.0"


def test_has_failures():
    r_pass = EndpointResult(method="GET", path="/a", http_status_code=200, response_time_ms=10)
    r_fail = EndpointResult(method="GET", path="/b", http_status_code=500, response_time_ms=10)
    validate_results([r_pass, r_fail])

    report_ok = Report([r_pass], spec_url="s", swagger_ui_url="u", base_url="b")
    assert not report_ok.has_failures

    report_bad = Report([r_pass, r_fail], spec_url="s", swagger_ui_url="u", base_url="b")
    assert report_bad.has_failures
