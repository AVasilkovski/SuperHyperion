"""
Eval CLI — Phase 16.7

Runs a smoke-test evaluation suite to collect pipeline performance
and correctness metrics.

Usage:
    superhyperion eval --suite smoke --n 3
    superhyperion eval --suite smoke --n 5 --json

Collects metrics:
  - primacy_fail_rate: fraction of runs that failed ledger primacy
  - hold_rate: fraction of runs held by governance gate
  - avg_evidence_count: mean evidence IDs per run
  - avg_claim_count: mean atomic claims per run
  - capsule_rate: fraction of runs that produced a run capsule

Outputs JSONL per-run and a final summary.
"""

import asyncio
import hashlib
import json as json_lib
import time
from typing import List

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

eval_app = typer.Typer(
    name="eval",
    help="Evaluate pipeline performance and correctness",
    no_args_is_help=True,
)

console = Console()

# Smoke-test queries: representative science questions
SMOKE_QUERIES = [
    "Does aspirin reduce inflammation through COX-2 inhibition?",
    "What is the role of p53 in tumor suppression?",
    "How does caffeine affect adenosine receptors?",
    "What causes insulin resistance in type 2 diabetes?",
    "Does metformin activate AMPK signaling?",
    "What is the mechanism of action of statins?",
    "How do CRISPR-Cas9 guide RNAs achieve specificity?",
    "What role does BDNF play in neuroplasticity?",
    "Does intermittent fasting affect autophagy?",
    "What is the connection between gut microbiome and immune function?",
]


async def _run_single_eval(query: str, run_index: int) -> dict:
    """
    Run a single evaluation pass through the pipeline.

    Returns a metrics dict for this run.
    """
    from src.graph.state import create_initial_state

    metrics = {
        "run_index": run_index,
        "query": query,
        "query_hash": hashlib.sha256(query.encode()).hexdigest()[:16],
        "status": "ERROR",
        "hold_code": None,
        "evidence_count": 0,
        "claim_count": 0,
        "has_capsule": False,
        "capsule_id": None,
        "latency_ms": 0,
    }

    start = time.perf_counter()

    try:
        from src.graph.workflow_v21 import build_v21_workflow

        state = create_initial_state(query)
        # Compile workflow
        app = build_v21_workflow().compile()

        # Run the workflow
        result = await app.ainvoke(state)

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        metrics["latency_ms"] = elapsed_ms

        # Extract metrics from result
        gov = result.get("governance", {}) or {}
        grounded = result.get("grounded_response", {}) or {}

        if gov.get("status") == "HOLD":
            metrics["status"] = "HOLD"
            metrics["hold_code"] = gov.get("hold_code")
        elif grounded.get("status") == "HOLD":
            metrics["status"] = "HOLD"
            metrics["hold_code"] = grounded.get("hold_code")
        elif result.get("response") and "HOLD" not in result["response"]:
            metrics["status"] = "PASS"
        else:
            metrics["status"] = "HOLD"

        metrics["evidence_count"] = len(gov.get("persisted_evidence_ids", []))

        gc = result.get("graph_context", {}) or {}
        metrics["claim_count"] = len(gc.get("atomic_claims", []))

        capsule = result.get("run_capsule")
        if capsule:
            metrics["has_capsule"] = True
            metrics["capsule_id"] = capsule.get("capsule_id")

    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        metrics["latency_ms"] = elapsed_ms
        metrics["status"] = "ERROR"
        metrics["hold_code"] = str(e)[:100]

    return metrics


def _compute_summary(results: List[dict]) -> dict:
    """Compute aggregate metrics from individual run results."""
    n = len(results)
    if n == 0:
        return {"total_runs": 0}

    pass_count = sum(1 for r in results if r["status"] == "PASS")
    hold_count = sum(1 for r in results if r["status"] == "HOLD")
    error_count = sum(1 for r in results if r["status"] == "ERROR")
    capsule_count = sum(1 for r in results if r["has_capsule"])

    evidence_counts = [r["evidence_count"] for r in results]
    claim_counts = [r["claim_count"] for r in results]
    latencies = [r["latency_ms"] for r in results]

    # Hold codes breakdown
    hold_codes = {}
    for r in results:
        if r["hold_code"]:
            hold_codes[r["hold_code"]] = hold_codes.get(r["hold_code"], 0) + 1

    return {
        "total_runs": n,
        "pass_count": pass_count,
        "hold_count": hold_count,
        "error_count": error_count,
        "pass_rate": round(pass_count / n, 3),
        "hold_rate": round(hold_count / n, 3),
        "error_rate": round(error_count / n, 3),
        "capsule_rate": round(capsule_count / n, 3),
        "avg_evidence_count": round(sum(evidence_counts) / n, 1),
        "avg_claim_count": round(sum(claim_counts) / n, 1),
        "avg_latency_ms": round(sum(latencies) / n, 0),
        "min_latency_ms": min(latencies) if latencies else 0,
        "max_latency_ms": max(latencies) if latencies else 0,
        "hold_codes": hold_codes,
    }


def _export_telemetry(summary: dict):
    """EPI-17.1: Export evaluation telemetry to CI artifacts."""
    import os
    from datetime import datetime

    artifact_dir = "ci_artifacts"
    os.makedirs(artifact_dir, exist_ok=True)
    telemetry_file = os.path.join(artifact_dir, "telemetry_trends.json")

    telemetry_data = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "metrics": summary,
        "git_commit": os.environ.get("GITHUB_SHA", "unknown"),
    }

    # Append to existing file or create new
    trends = []
    if os.path.exists(telemetry_file):
        try:
            with open(telemetry_file, "r") as f:
                trends = json_lib.load(f)
        except Exception as e:
            console.print(
                f"[yellow]Warning: Could not read existing telemetry trends: {e}[/yellow]"
            )

    trends.append(telemetry_data)

    # Keep only last 100 entries for manageable artifact size
    if len(trends) > 100:
        trends = trends[-100:]

    try:
        with open(telemetry_file, "w") as f:
            json_lib.dump(trends, f, indent=2)
        console.print(f"  [dim]Telemetry exported to {telemetry_file}[/dim]")
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to export telemetry: {e}[/yellow]")


@eval_app.command("run")
def run_eval(
    suite: str = typer.Option(
        "smoke",
        "--suite",
        "-s",
        help="Evaluation suite to run (smoke)",
    ),
    n: int = typer.Option(
        3,
        "--n",
        help="Number of queries to evaluate",
        min=1,
        max=100,
    ),
    json: bool = typer.Option(
        False,
        "--json",
        help="Output as JSONL (one line per run + summary)",
    ),
    output_file: str = typer.Option(
        None,
        "--output",
        "-o",
        help="Write JSONL results to file",
    ),
):
    """Run pipeline evaluation suite and collect metrics."""
    if suite != "smoke":
        console.print(f"[red]Unknown suite: {suite}[/red]")
        console.print("Available: smoke")
        raise typer.Exit(1)

    queries = SMOKE_QUERIES[:n]
    console.print(f"\n[bold]Eval Suite:[/bold] {suite} ({len(queries)} queries)\n")

    results: List[dict] = []
    jsonl_lines: List[str] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Running evaluations...", total=len(queries))

        for i, query in enumerate(queries):
            progress.update(task, description=f"[{i + 1}/{len(queries)}] {query[:50]}...")

            result = asyncio.run(_run_single_eval(query, i))
            results.append(result)

            if json or output_file:
                line = json_lib.dumps(result, default=str)
                jsonl_lines.append(line)

            progress.advance(task)

    # Compute summary
    summary = _compute_summary(results)

    # EPI-17.1 Telemetry Export
    _export_telemetry(summary)

    if output_file:
        with open(output_file, "w") as f:
            for line in jsonl_lines:
                f.write(line + "\n")
            f.write(json_lib.dumps({"_summary": summary}, default=str) + "\n")
        console.print(f"[green]Results written to:[/green] {output_file}")

    if json:
        for line in jsonl_lines:
            print(line)
        print(json_lib.dumps({"_summary": summary}, default=str))
        return

    # Rich summary table
    console.print()

    # Per-run results
    run_table = Table(title="Per-Run Results")
    run_table.add_column("#", justify="right", style="dim")
    run_table.add_column("Query", max_width=40)
    run_table.add_column("Status")
    run_table.add_column("Evidence", justify="right")
    run_table.add_column("Claims", justify="right")
    run_table.add_column("Capsule")
    run_table.add_column("Latency", justify="right")

    for r in results:
        status_style = {
            "PASS": "[green]PASS[/green]",
            "HOLD": f"[yellow]HOLD[/yellow] ({r['hold_code'] or '?'})",
            "ERROR": "[red]ERROR[/red]",
        }.get(r["status"], r["status"])

        run_table.add_row(
            str(r["run_index"]),
            r["query"][:40],
            status_style,
            str(r["evidence_count"]),
            str(r["claim_count"]),
            "✓" if r["has_capsule"] else "-",
            f"{r['latency_ms']}ms",
        )

    console.print(run_table)

    # Summary panel
    summary_text = f"""[bold]Total Runs:[/bold] {summary["total_runs"]}
[bold]Pass Rate:[/bold] {summary["pass_rate"]:.1%}
[bold]Hold Rate:[/bold] {summary["hold_rate"]:.1%}
[bold]Error Rate:[/bold] {summary["error_rate"]:.1%}
[bold]Capsule Rate:[/bold] {summary["capsule_rate"]:.1%}
[bold]Avg Evidence/Run:[/bold] {summary["avg_evidence_count"]}
[bold]Avg Claims/Run:[/bold] {summary["avg_claim_count"]}
[bold]Avg Latency:[/bold] {summary["avg_latency_ms"]:.0f}ms ({summary["min_latency_ms"]}–{summary["max_latency_ms"]}ms)"""

    if summary["hold_codes"]:
        summary_text += "\n\n[bold]Hold Codes:[/bold]"
        for code, count in sorted(summary["hold_codes"].items(), key=lambda x: -x[1]):
            summary_text += f"\n  {code}: {count}"

    console.print(Panel(summary_text, title="Evaluation Summary", border_style="blue"))
