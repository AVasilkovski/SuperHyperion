"""SuperHyperion Prompts"""

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    """Load a prompt template by name."""
    path = PROMPTS_DIR / f"{name}.txt"
    if path.exists():
        return path.read_text()
    raise FileNotFoundError(f"Prompt not found: {name}")


# Pre-load common prompts
CODEACT_SYSTEM = load_prompt("codeact_system")
SOCRATIC_CRITIC = load_prompt("socratic_critic")

__all__ = [
    "load_prompt",
    "CODEACT_SYSTEM",
    "SOCRATIC_CRITIC",
    "PROMPTS_DIR",
]
