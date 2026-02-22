"""Compliance report CLI over bundle exports only."""

from __future__ import annotations

import json

import typer

from src.sdk.compliance import write_compliance_outputs

compliance_app = typer.Typer(
    name="compliance", help="Compliance reporting tools", no_args_is_help=True
)


@compliance_app.command("report")
def report(
    bundles: str = typer.Option(
        ..., "--bundles", help="Directory containing exported bundle artifacts"
    ),
    out: str = typer.Option(..., "--out", help="Output path or directory"),
    fmt: str = typer.Option("json", "--format", help="json or csv"),
    tenant: str | None = typer.Option(None, "--tenant", help="Optional tenant filter"),
    p95_min_sample_size: int = typer.Option(
        30, "--p95-min-sample-size", help="Minimum sample size for p95"
    ),
):
    include_csv = fmt.lower() == "csv"
    written = write_compliance_outputs(
        bundles_dir=bundles,
        out_path=out,
        include_csv=include_csv,
        tenant_id=tenant,
        p95_min_sample_size=p95_min_sample_size,
    )
    print(json.dumps({"written": written}, indent=2))
