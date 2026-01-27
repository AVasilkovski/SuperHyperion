"""
Intent CLI Subcommands

Thin wrapper over WriteIntentService.
No business logic — just command parsing and output formatting.
"""

import json as json_lib
from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax

from src.hitl.intent_service import (
    WriteIntentService,
    IntentStatus,
    IntentTransitionError,
    IntentNotFoundError,
    ScopeLockRequiredError,
)
from src.cli.wiring import get_service

# Create subcommand app
intent_app = typer.Typer(
    name="intent",
    help="Manage write-intents",
    no_args_is_help=True,
)

console = Console()


# =============================================================================
# List Command
# =============================================================================

@intent_app.command("list")
def list_intents(
    status: Optional[str] = typer.Option(
        None,
        "--status", "-s",
        help="Filter by status (staged, awaiting_hitl, approved, rejected, etc.)",
    ),
    limit: int = typer.Option(
        50,
        "--limit", "-l",
        help="Maximum number of intents to show",
    ),
    json: bool = typer.Option(
        False,
        "--json",
        help="Output as JSON",
    ),
):
    """List write-intents, optionally filtered by status."""
    service = get_service()
    
    if status:
        try:
            status_enum = IntentStatus(status)
            intents = service.list_by_status(status_enum)
        except ValueError:
            console.print(f"[red]Invalid status: {status}[/red]")
            console.print(f"Valid: {', '.join(s.value for s in IntentStatus)}")
            raise typer.Exit(1)
    else:
        # List all non-terminal (pending review)
        intents = service.list_pending()
    
    intents = intents[:limit]
    
    if json:
        output = [i.to_dict() for i in intents]
        print(json_lib.dumps(output, indent=2, default=str))
        return
    
    if not intents:
        console.print("[dim]No intents found[/dim]")
        return
    
    table = Table(title=f"Write-Intents ({len(intents)})")
    table.add_column("Intent ID", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Impact", justify="right")
    table.add_column("Scope Lock")
    table.add_column("Expires At")
    
    for i in intents:
        expires = i.expires_at.strftime("%Y-%m-%d %H:%M") if i.expires_at else "-"
        table.add_row(
            i.intent_id,
            i.intent_type,
            i.status.value,
            f"{i.impact_score:.2f}",
            i.scope_lock_id or "-",
            expires,
        )
    
    console.print(table)


# =============================================================================
# Show Command
# =============================================================================

@intent_app.command("show")
def show_intent(
    intent_id: str = typer.Argument(..., help="Intent ID to show"),
    history: bool = typer.Option(
        False,
        "--history", "-h",
        help="Include event history",
    ),
    json: bool = typer.Option(
        False,
        "--json",
        help="Output as JSON",
    ),
):
    """Show details of a specific intent."""
    service = get_service()
    
    intent = service.get(intent_id)
    if not intent:
        console.print(f"[red]Intent not found: {intent_id}[/red]")
        raise typer.Exit(1)
    
    events = []
    if history:
        events = service.get_history(intent_id)
    
    if json:
        output = {
            "intent": intent.to_dict(),
            "history": [e.to_dict() for e in events] if history else [],
        }
        print(json_lib.dumps(output, indent=2, default=str))
        return
    
    # Rich output
    panel_content = f"""[bold]Intent ID:[/bold] {intent.intent_id}
[bold]Type:[/bold] {intent.intent_type}
[bold]Status:[/bold] {intent.status.value}
[bold]Impact Score:[/bold] {intent.impact_score:.2f}
[bold]Scope Lock:[/bold] {intent.scope_lock_id or "None"}
[bold]Created:[/bold] {intent.created_at.isoformat()}
[bold]Expires:[/bold] {intent.expires_at.isoformat() if intent.expires_at else "Never"}
[bold]Supersedes:[/bold] {intent.supersedes_intent_id or "None"}"""
    
    console.print(Panel(panel_content, title="Intent Details", border_style="blue"))
    
    # Payload
    if intent.payload:
        payload_json = json_lib.dumps(intent.payload, indent=2, default=str)
        console.print("\n[bold]Payload:[/bold]")
        console.print(Syntax(payload_json, "json", theme="monokai"))
    
    # History
    if history and events:
        console.print("\n[bold]Event History:[/bold]")
        history_table = Table()
        history_table.add_column("Time", style="dim")
        history_table.add_column("From", style="yellow")
        history_table.add_column("To", style="green")
        history_table.add_column("Actor")
        history_table.add_column("Rationale")
        
        for e in events:
            history_table.add_row(
                e.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                e.from_status.value,
                e.to_status.value,
                f"{e.actor_type}:{e.actor_id}",
                e.rationale or "-",
            )
        
        console.print(history_table)


# =============================================================================
# Approve Command
# =============================================================================

@intent_app.command("approve")
def approve_intent(
    intent_id: str = typer.Argument(..., help="Intent ID to approve"),
    by: str = typer.Option(
        ...,
        "--by", "-b",
        help="Approver ID (required)",
    ),
    why: str = typer.Option(
        ...,
        "--why", "-w",
        help="Rationale for approval (required)",
    ),
):
    """Approve an intent for execution."""
    service = get_service()
    
    try:
        intent = service.approve(intent_id, approver_id=by, rationale=why)
        console.print(f"[green]✓ Approved:[/green] {intent.intent_id}")
        console.print(f"  Status: {intent.status.value}")
    except IntentNotFoundError:
        console.print(f"[red]Intent not found: {intent_id}[/red]")
        raise typer.Exit(1)
    except IntentTransitionError as e:
        console.print(f"[red]Transition error:[/red] {e}")
        raise typer.Exit(1)


# =============================================================================
# Reject Command
# =============================================================================

@intent_app.command("reject")
def reject_intent(
    intent_id: str = typer.Argument(..., help="Intent ID to reject"),
    by: str = typer.Option(
        ...,
        "--by", "-b",
        help="Rejector ID (required)",
    ),
    why: str = typer.Option(
        ...,
        "--why", "-w",
        help="Rationale for rejection (required)",
    ),
):
    """Reject an intent (terminal)."""
    service = get_service()
    
    try:
        intent = service.reject(intent_id, rejector_id=by, rationale=why)
        console.print(f"[red]✗ Rejected:[/red] {intent.intent_id}")
        console.print(f"  Status: {intent.status.value}")
    except IntentNotFoundError:
        console.print(f"[red]Intent not found: {intent_id}[/red]")
        raise typer.Exit(1)
    except IntentTransitionError as e:
        console.print(f"[red]Transition error:[/red] {e}")
        raise typer.Exit(1)


# =============================================================================
# Defer Command
# =============================================================================

@intent_app.command("defer")
def defer_intent(
    intent_id: str = typer.Argument(..., help="Intent ID to defer"),
    by: str = typer.Option(
        ...,
        "--by", "-b",
        help="Deferrer ID (required)",
    ),
    until: str = typer.Option(
        ...,
        "--until", "-u",
        help="ISO datetime to defer until (required, e.g. 2026-02-01T10:00:00Z)",
    ),
    why: str = typer.Option(
        ...,
        "--why", "-w",
        help="Rationale for deferral (required)",
    ),
):
    """Defer an intent for later review."""
    service = get_service()
    
    try:
        until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
    except ValueError:
        console.print(f"[red]Invalid datetime format: {until}[/red]")
        console.print("Expected ISO format: 2026-02-01T10:00:00Z")
        raise typer.Exit(1)
    
    try:
        intent = service.defer(intent_id, deferrer_id=by, until=until_dt, rationale=why)
        console.print(f"[yellow]⏸ Deferred:[/yellow] {intent.intent_id}")
        console.print(f"  Until: {until_dt.isoformat()}")
    except IntentNotFoundError:
        console.print(f"[red]Intent not found: {intent_id}[/red]")
        raise typer.Exit(1)
    except IntentTransitionError as e:
        console.print(f"[red]Transition error:[/red] {e}")
        raise typer.Exit(1)


# =============================================================================
# Cancel Command
# =============================================================================

@intent_app.command("cancel")
def cancel_intent(
    intent_id: str = typer.Argument(..., help="Intent ID to cancel"),
    by: str = typer.Option(
        ...,
        "--by", "-b",
        help="Canceller ID (required)",
    ),
    why: str = typer.Option(
        ...,
        "--why", "-w",
        help="Rationale for cancellation (required)",
    ),
):
    """Cancel an intent (terminal)."""
    service = get_service()
    
    try:
        intent = service.cancel(intent_id, actor_id=by, rationale=why)
        console.print(f"[dim]⊘ Cancelled:[/dim] {intent.intent_id}")
        console.print(f"  Status: {intent.status.value}")
    except IntentNotFoundError:
        console.print(f"[red]Intent not found: {intent_id}[/red]")
        raise typer.Exit(1)
    except IntentTransitionError as e:
        console.print(f"[red]Transition error:[/red] {e}")
        raise typer.Exit(1)


# =============================================================================
# Expire-Stale Command
# =============================================================================

@intent_app.command("expire-stale")
def expire_stale(
    max_age_days: int = typer.Option(
        7,
        "--max-age-days",
        help="Maximum age in days before expiring",
    ),
    actor: str = typer.Option(
        "system",
        "--actor",
        help="Actor ID for audit trail",
    ),
    json: bool = typer.Option(
        False,
        "--json",
        help="Output as JSON",
    ),
):
    """Expire all stale intents past their expiry date."""
    service = get_service()
    
    expired_ids = service.expire_stale(max_age_days=max_age_days)
    
    if json:
        print(json_lib.dumps({"expired": expired_ids}))
        return
    
    if not expired_ids:
        console.print("[dim]No stale intents to expire[/dim]")
        return
    
    console.print(f"[yellow]Expired {len(expired_ids)} intent(s):[/yellow]")
    for eid in expired_ids:
        console.print(f"  • {eid}")
