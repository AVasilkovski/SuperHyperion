"""
SuperHyperion CLI — Main Entry Point

Usage:
    superhyperion intent list --status awaiting_hitl
    superhyperion intent approve <intent_id> --by "Anton" --why "..."
    superhyperion replay verify --run-id <capsule-id>
    superhyperion eval run --suite smoke --n 3
"""

import typer
from rich.console import Console

from src.cli.intent_cli import intent_app
from src.cli.replay_cli import replay_app
from src.cli.eval_cli import eval_app

# Create main app
app = typer.Typer(
    name="superhyperion",
    help="Constitutional knowledge verification system",
    no_args_is_help=True,
)

# Register subcommands
app.add_typer(intent_app, name="intent", help="Manage write-intents")
app.add_typer(replay_app, name="replay", help="Verify past run capsules")
app.add_typer(eval_app, name="eval", help="Evaluate pipeline performance")

# Console for output
console = Console()


@app.callback()
def main_callback():
    """SuperHyperion — Constitutional knowledge verification system."""
    pass


@app.command()
def version():
    """Show version information."""
    console.print("[bold]SuperHyperion[/bold] v2.2.0")
    console.print("Constitutional knowledge verification system")


if __name__ == "__main__":
    app()
