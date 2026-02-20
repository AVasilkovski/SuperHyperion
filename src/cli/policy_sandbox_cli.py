"""Policy sandbox simulation CLI."""

from __future__ import annotations

import json

import typer

from src.sdk.sandbox import simulate_policies

policy_app = typer.Typer(name="policy", help="Local policy sandbox tools", no_args_is_help=True)


@policy_app.command("simulate")
def simulate(
    bundles: str = typer.Option(..., "--bundles", help="Directory containing exported bundle artifacts"),
    policies: str = typer.Option(..., "--policies", help="Python module path exposing policy callables"),
    out: str = typer.Option(..., "--out", help="Output directory for policy simulation artifacts"),
    json_output: bool = typer.Option(False, "--json", help="Output JSON summary"),
):
    written = simulate_policies(bundles_dir=bundles, policies_module=policies, out_dir=out)
    if json_output:
        print(json.dumps({"written": written}, indent=2))
    else:
        for path in written:
            typer.echo(path)
