"""
Replay CLI — Phase 16.7

Verifies a past run capsule against the ledger.

Usage:
    superhyperion replay --run-id <capsule-id>

Fetches the capsule manifest from TypeDB, re-runs primacy verification
against current ledger state, recomputes the manifest hash, and emits
a PASS/FAIL verdict.
"""

import json as json_lib
import hashlib

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

replay_app = typer.Typer(
    name="replay",
    help="Verify past run capsules against the ledger",
    no_args_is_help=True,
)

console = Console()


def _fetch_capsule(capsule_id: str) -> dict | None:
    """Fetch a run-capsule from TypeDB by capsule-id."""
    try:
        from src.db.typedb_client import TypeDBConnection
        db = TypeDBConnection()
        if db._mock_mode:
            console.print("[yellow]⚠ TypeDB unavailable (mock mode)[/yellow]")
            return None

        _esc = lambda s: (str(s) or "").replace("\\", "\\\\").replace('"', '\\"')
        query = f'''
        match
            $cap isa run-capsule,
                has capsule-id $cid,
                has session-id $sid,
                has query-hash $qh,
                has scope-lock-id $slid,
                has intent-id $iid,
                has proposal-id $pid,
                has evidence-snapshot $esnap,
                has capsule-hash $chash;
            $cid == "{_esc(capsule_id)}";
        get $cid, $sid, $qh, $slid, $iid, $pid, $esnap, $chash;
        '''
        rows = db.query_fetch(query)
        if not rows:
            return None

        row = rows[0]
        return {
            "capsule_id": row.get("cid"),
            "session_id": row.get("sid"),
            "query_hash": row.get("qh"),
            "scope_lock_id": row.get("slid"),
            "intent_id": row.get("iid"),
            "proposal_id": row.get("pid"),
            "evidence_ids": json_lib.loads(row.get("esnap", "[]")),
            "capsule_hash": row.get("chash"),
        }
    except Exception as e:
        console.print(f"[red]TypeDB error:[/red] {e}")
        return None


def _recompute_capsule_hash(capsule_id: str, manifest: dict) -> str:
    """Recompute capsule manifest hash for integrity check."""
    from src.governance.fingerprinting import make_capsule_manifest_hash
    return make_capsule_manifest_hash(capsule_id, manifest)


@replay_app.command("verify")
def verify_run(
    run_id: str = typer.Option(
        ...,
        "--run-id", "-r",
        help="Run capsule ID to verify",
    ),
    json: bool = typer.Option(
        False,
        "--json",
        help="Output as JSON",
    ),
):
    """Verify a past run capsule against the ledger."""
    console.print(f"\n[bold]Replaying run:[/bold] {run_id}\n")

    # 1. Fetch capsule
    capsule = _fetch_capsule(run_id)
    if not capsule:
        console.print(f"[red]✗ Capsule not found:[/red] {run_id}")
        console.print("  Ensure TypeDB is running and the capsule exists.")
        raise typer.Exit(1)

    console.print(f"  [green]✓[/green] Capsule found (session: {capsule['session_id']})")

    # 2. Integrity check: recompute hash
    manifest = {
        "session_id": capsule["session_id"],
        "query_hash": capsule["query_hash"],
        "scope_lock_id": capsule["scope_lock_id"],
        "intent_id": capsule["intent_id"],
        "proposal_id": capsule["proposal_id"],
        "evidence_ids": sorted(capsule["evidence_ids"]),
    }
    recomputed_hash = _recompute_capsule_hash(run_id, manifest)
    hash_match = recomputed_hash == capsule["capsule_hash"]

    if hash_match:
        console.print("  [green]✓[/green] Manifest hash integrity: PASS")
    else:
        console.print("  [red]✗[/red] Manifest hash integrity: FAIL")
        console.print(f"    Expected: {capsule['capsule_hash']}")
        console.print(f"    Got:      {recomputed_hash}")

    # 3. Re-run primacy verification
    from src.agents.integrator_agent import integrator_agent

    primacy_ok, primacy_code, primacy_details = integrator_agent._verify_evidence_primacy(
        session_id=capsule["session_id"],
        evidence_ids=capsule["evidence_ids"],
        expected_scope_lock_id=capsule["scope_lock_id"],
    )

    if primacy_ok:
        console.print(f"  [green]✓[/green] Ledger primacy: PASS ({primacy_details.get('verified_count', 0)} evidence IDs)")
    else:
        console.print(f"  [red]✗[/red] Ledger primacy: FAIL [{primacy_code}]")
        if primacy_details.get("hold_reason"):
            console.print(f"    {primacy_details['hold_reason']}")

    # 4. Overall verdict
    overall = hash_match and primacy_ok
    verdict = "PASS" if overall else "FAIL"

    if json:
        result = {
            "capsule_id": run_id,
            "verdict": verdict,
            "hash_integrity": "PASS" if hash_match else "FAIL",
            "primacy": "PASS" if primacy_ok else "FAIL",
            "primacy_code": primacy_code,
            "primacy_details": primacy_details,
            "capsule": capsule,
        }
        print(json_lib.dumps(result, indent=2, default=str))
        return

    console.print()
    if overall:
        console.print(Panel(
            f"[bold green]PASS[/bold green] — Run {run_id} is reproducible and ledger-anchored.",
            border_style="green",
        ))
    else:
        failures = []
        if not hash_match:
            failures.append("manifest integrity")
        if not primacy_ok:
            failures.append(f"ledger primacy ({primacy_code})")
        console.print(Panel(
            f"[bold red]FAIL[/bold red] — {', '.join(failures)}",
            border_style="red",
        ))

    raise typer.Exit(0 if overall else 1)
