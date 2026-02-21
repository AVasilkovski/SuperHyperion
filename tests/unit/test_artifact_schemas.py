from __future__ import annotations

import json
from pathlib import Path

SCHEMAS = [
    "schemas/trust_gate_summary.v1.schema.json",
    "schemas/policy_conflicts_summary.v1.schema.json",
    "schemas/compliance_report.v1.schema.json",
]


def test_artifact_schema_files_exist_and_are_valid_json():
    for rel in SCHEMAS:
        path = Path(rel)
        assert path.exists(), f"missing schema: {rel}"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["$schema"].startswith("https://json-schema.org/")
        assert payload["type"] == "object"
