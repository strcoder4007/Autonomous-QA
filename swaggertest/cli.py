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


if __name__ == "__main__":
    app()
