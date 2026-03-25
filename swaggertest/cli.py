"""CLI entrypoint using Typer."""

from __future__ import annotations

import json
import sys
from typing import Optional

import typer

app = typer.Typer(name="swaggertest", help="Swagger API Test Tool")


@app.command("parse")
def parse_cmd(
    url: str = typer.Option(..., "--url", help="Swagger UI URL"),
) -> None:
    """Discover and parse the OpenAPI spec, then print all endpoints."""
    from swaggertest.parser import SpecParser

    try:
        spec = SpecParser(url=url)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2)

    endpoints = spec.get_endpoints()
    typer.echo(f"Spec URL: {spec.spec_url}")
    typer.echo(f"Endpoints found: {len(endpoints)}\n")
    for ep in endpoints:
        params = ", ".join(
            f"{p.name} ({'required' if p.required else 'optional'}, in {p.location})"
            for p in ep.parameters
        )
        typer.echo(f"  {ep.method:7s} {ep.path}")
        if ep.summary:
            typer.echo(f"          {ep.summary}")
        if params:
            typer.echo(f"          Params: {params}")
        typer.echo(f"          Responses: {', '.join(ep.response_codes)}")
        typer.echo()


@app.command("run")
def run_cmd(
    url: str = typer.Option(..., "--url", help="Swagger UI URL"),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Base URL for API requests"),
    output: Optional[str] = typer.Option(None, "--output", help="Path to write JSON report"),
    seed_params: Optional[str] = typer.Option(None, "--seed-params", help="Path to seed params JSON file"),
    config: str = typer.Option(".swaggertest.yaml", "--config", help="Path to config file"),
) -> None:
    """Discover spec, execute GET requests, validate responses, and produce a JSON report."""
    from swaggertest.config import load_config
    from swaggertest.parser import SpecParser
    from swaggertest.reporter import Report
    from swaggertest.runner import Runner
    from swaggertest.validator import validate_results

    try:
        spec = SpecParser(url=url)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2)

    try:
        cfg = load_config(
            cli_base_url=base_url,
            cli_seed_params=seed_params,
            config_path=config,
        )
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2)

    if not cfg.base_url:
        typer.echo(
            "ERROR: BASE_URL is required for 'run' but was not found in CLI flags, .env, or "
            ".swaggertest.yaml. Set it explicitly to avoid accidentally hitting production.",
            err=True,
        )
        raise typer.Exit(code=2)

    runner = Runner(spec, config=cfg)
    results = runner.run()
    validate_results(results)

    report = Report(
        results,
        spec_url=spec.spec_url,
        swagger_ui_url=spec.swagger_ui_url,
        base_url=cfg.base_url,
    )

    report_dict = report.to_dict()
    meta = report_dict["meta"]

    typer.echo(f"Spec URL:    {meta['spec_url']}")
    typer.echo(f"Base URL:    {meta['base_url']}")
    typer.echo(f"Total:       {meta['total_in_spec']}")
    typer.echo(f"Attempted:   {meta['total_attempted']}")
    typer.echo(f"Passed:      {meta['passed']}")
    typer.echo(f"Failed:      {meta['failed']}")
    typer.echo(f"Skipped (no param):  {meta['skipped_no_param']}")
    typer.echo(f"Skipped (non-GET):   {meta['skipped_non_get']}")

    if output:
        report.save(output)
        typer.echo(f"\nReport saved to {output}")
    else:
        typer.echo("\n" + json.dumps(report_dict, indent=2))

    if report.has_failures:
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)


@app.command("generate")
def generate_cmd(
    spec: str = typer.Option(..., "--spec", help="Path to local OpenAPI spec file (JSON or YAML)"),
    tickets: str = typer.Option(..., "--tickets", help="Path to ticket CSV/XLSX file"),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Base URL for test execution"),
    output: str = typer.Option("test_cases.json", "--output", help="Output path for generated test cases"),
    execute: bool = typer.Option(False, "--execute", help="Execute tests after generation"),
    report: Optional[str] = typer.Option(None, "--report", help="Execution report output path"),
    model: Optional[str] = typer.Option(None, "--model", help="Override LLM model"),
    batch_size: Optional[int] = typer.Option(None, "--batch-size", help="Tickets per LLM batch"),
    config: str = typer.Option(".swaggertest.yaml", "--config", help="Path to config file"),
) -> None:
    """Match tickets to API endpoints, generate test cases, and optionally execute them."""
    from swaggertest.config import load_config
    from swaggertest.generator import generate_test_cases
    from swaggertest.llm_client import LLMClient
    from swaggertest.matcher import match_tickets_to_endpoints
    from swaggertest.parser import SpecParser
    from swaggertest.ticket_reader import read_tickets
    from swaggertest.testcase_io import save_test_cases

    # --- Load config ---
    try:
        cfg = load_config(cli_base_url=base_url, config_path=config)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2)

    if execute and not cfg.base_url:
        typer.echo(
            "ERROR: --execute requires a base URL. Set --base-url, BASE_URL in .env, or "
            "base_url in .swaggertest.yaml.",
            err=True,
        )
        raise typer.Exit(code=2)

    # --- Step 1: Read ticket file ---
    try:
        ticket_rows = read_tickets(tickets)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        typer.echo(f"ERROR reading ticket file: {exc}", err=True)
        raise typer.Exit(code=2)
    typer.echo(f"Read {len(ticket_rows)} tickets from file.")

    # --- Step 2: Parse spec (abort before any LLM call if this fails) ---
    try:
        parser = SpecParser.from_file(spec)
    except (FileNotFoundError, RuntimeError) as exc:
        typer.echo(f"ERROR reading spec file: {exc}", err=True)
        raise typer.Exit(code=2)
    endpoints = parser.get_endpoints()
    typer.echo(f"Parsed spec: {len(endpoints)} endpoints found.")

    # --- LLM client ---
    llm_model = model or cfg.llm.model
    llm_batch = batch_size or cfg.llm.batch_size
    llm = LLMClient(
        model=llm_model,
        max_tokens=cfg.llm.max_tokens,
        temperature=cfg.llm.temperature,
    )

    # --- Step 3: Match ---
    typer.echo(f"\nMatching {len(ticket_rows)} tickets to {len(endpoints)} endpoints (batch={llm_batch})...")
    matches = match_tickets_to_endpoints(ticket_rows, endpoints, llm, batch_size=llm_batch)
    typer.echo(f"Matched {len(matches)}/{len(ticket_rows)} tickets to endpoints.")

    # --- Step 4: Generate ---
    typer.echo(f"\nGenerating test cases for {len(matches)} matched tickets...")
    test_cases = generate_test_cases(matches, endpoints, llm, batch_size=3)
    typer.echo(f"Generated {len(test_cases)} test cases.")

    # --- Step 5: Save ---
    save_test_cases(
        test_cases,
        output,
        rally_source=tickets,
        spec_source=spec,
        llm_usage=llm.usage,
    )
    typer.echo(f"\nTest cases saved to {output}")
    typer.echo(llm.usage_summary())

    # --- Step 6: Execute (optional) ---
    if execute:
        from dataclasses import asdict
        from swaggertest.runner import TestCaseRunner

        typer.echo(f"\nExecuting {len(test_cases)} test cases against {cfg.base_url}...")
        runner = TestCaseRunner(cfg)
        results = runner.run(test_cases)

        passed = sum(1 for r in results if r.status == "passed")
        failed = sum(1 for r in results if r.status == "failed")
        errors = sum(1 for r in results if r.status == "error")
        typer.echo(f"Results: {passed} passed, {failed} failed, {errors} errors")

        if report:
            import json as _json
            report_data = {
                "test_case_results": [asdict(r) for r in results],
                "summary": {"passed": passed, "failed": failed, "errors": errors},
            }
            import pathlib
            pathlib.Path(report).write_text(_json.dumps(report_data, indent=2), encoding="utf-8")
            typer.echo(f"Execution report saved to {report}")

        if failed > 0 or errors > 0:
            raise typer.Exit(code=1)

    raise typer.Exit(code=0)


@app.command("match")
def match_cmd(
    spec: str = typer.Option(..., "--spec", help="Path to local OpenAPI spec file (JSON or YAML)"),
    tickets: str = typer.Option(..., "--tickets", help="Path to ticket CSV/XLSX file"),
    model: Optional[str] = typer.Option(None, "--model", help="Override LLM model"),
    config: str = typer.Option(".swaggertest.yaml", "--config", help="Path to config file"),
) -> None:
    """Preview ticket→endpoint matches and LLM cost without generating test cases."""
    from swaggertest.config import load_config
    from swaggertest.llm_client import LLMClient
    from swaggertest.matcher import match_tickets_to_endpoints
    from swaggertest.parser import SpecParser
    from swaggertest.ticket_reader import read_tickets

    try:
        cfg = load_config(config_path=config)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2)

    try:
        ticket_rows = read_tickets(tickets)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        typer.echo(f"ERROR reading ticket file: {exc}", err=True)
        raise typer.Exit(code=2)
    typer.echo(f"Read {len(ticket_rows)} tickets from file.")

    try:
        parser = SpecParser.from_file(spec)
    except (FileNotFoundError, RuntimeError) as exc:
        typer.echo(f"ERROR reading spec file: {exc}", err=True)
        raise typer.Exit(code=2)
    endpoints = parser.get_endpoints()
    typer.echo(f"Parsed spec: {len(endpoints)} endpoints.\n")

    llm_model = model or cfg.llm.model
    llm = LLMClient(model=llm_model, max_tokens=cfg.llm.max_tokens, temperature=cfg.llm.temperature)

    matches = match_tickets_to_endpoints(ticket_rows, endpoints, llm, batch_size=cfg.llm.batch_size)

    typer.echo(f"\nMatches ({len(matches)}/{len(ticket_rows)} tickets had endpoints):\n")
    for m in matches:
        typer.echo(f"  [{m.confidence.upper()}] {m.ticket_id}: {m.ticket_title[:60]}")
        for ep in m.matched_endpoints:
            typer.echo(f"    → {ep}")
        typer.echo(f"    Reason: {m.reasoning[:120]}")
        typer.echo()

    typer.echo(llm.usage_summary())
    raise typer.Exit(code=0)


if __name__ == "__main__":
    app()
