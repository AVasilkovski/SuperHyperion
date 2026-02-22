"""Policy sandbox and conflict tools CLI."""

from __future__ import annotations

import json

import typer

from src.sdk.policy_conflicts import run_policy_conflicts, should_fail_on_severity
from src.sdk.sandbox import simulate_policies

policy_app = typer.Typer(name="policy", help="Local policy sandbox tools", no_args_is_help=True)


@policy_app.command("simulate")
def simulate(
    bundles: str = typer.Option(
        ..., "--bundles", help="Directory containing exported bundle artifacts"
    ),
    policies: str = typer.Option(
        ..., "--policies", help="Python module path exposing policy callables"
    ),
    out: str = typer.Option(..., "--out", help="Output directory for policy simulation artifacts"),
    tenant: str | None = typer.Option(None, "--tenant", help="Optional tenant filter"),
    json_output: bool = typer.Option(False, "--json", help="Output JSON summary"),
):
    written = simulate_policies(
        bundles_dir=bundles, policies_module=policies, out_dir=out, tenant_id=tenant
    )
    if json_output:
        print(json.dumps({"written": written}, indent=2))
    else:
        for path in written:
            typer.echo(path)


@policy_app.command("conflicts")
def conflicts(
    bundles: str = typer.Option(
        ..., "--bundles", help="Directory containing exported bundle artifacts"
    ),
    policies: str = typer.Option(
        ..., "--policies", help="Python module path exposing policy callables"
    ),
    out: str = typer.Option(..., "--out", help="Output directory for policy conflict artifacts"),
    tenant: str | None = typer.Option(None, "--tenant", help="Optional tenant filter"),
    fail_on_severity: str = typer.Option(
        "none",
        "--fail-on-severity",
        help="Exit non-zero if conflicts meet threshold: none|error|warning",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output JSON summary"),
):
    written = run_policy_conflicts(
        bundles_dir=bundles, policies_module=policies, out_dir=out, tenant_id=tenant
    )
    summary_path = next((p for p in written if p.endswith("policy_conflicts_summary.json")), None)
    summary = None
    if summary_path:
        with open(summary_path, "r", encoding="utf-8") as fh:
            summary = json.load(fh)

    threshold = fail_on_severity.lower().strip()
    if threshold not in {"none", "error", "warning"}:
        raise typer.BadParameter("--fail-on-severity must be one of: none, error, warning")

    if json_output:
        payload = {"written": written}
        if summary is not None:
            payload["summary"] = summary
        print(json.dumps(payload, indent=2))
    else:
        for path in written:
            typer.echo(path)

    if summary is not None and should_fail_on_severity(summary, threshold):
        raise typer.Exit(code=1)
