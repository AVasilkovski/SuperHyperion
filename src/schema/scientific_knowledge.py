from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "scientific_knowledge.tql"
CANONICAL_SCHEMA = SCHEMA_PATH.read_text(encoding="utf-8")
