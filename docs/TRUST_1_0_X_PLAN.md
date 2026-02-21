# TRUST-1.0.x Plan — Explainability-First Overlay Strategy

## Why this plan

`make_capsule_manifest_hash()` is already key-filtered by allowed manifest keys, which enables safe delivery of new trust features as **non-hashed overlays** first. This avoids integrity drift while accelerating enterprise-facing UX and compliance outputs.

## Current audit bundle baseline (as implemented)

Current deterministic filenames:

1. `<prefix>_governance_summary.json`
2. `<prefix>_replay_verify_verdict.json` (when replay verdict is present)
3. `<prefix>_run_capsule_manifest.json` (when capsule exists)

Current schema shape highlights:

- `governance_summary.json`: direct `GovernanceSummaryV1` payload, including gate/hold context and stewardship metadata.
- `replay_verify_verdict.json`: `ReplayVerdictV1` payload with `status`, `reasons`, and structured verification `details`.
- `run_capsule_manifest.json`: SDK export envelope with capsule + tenant + IDs used by reviewers.

## Impact × Effort ordering (next cycle)

### P0
1. Deterministic replay harness in CI (`OPS-1.2`)
2. Explainability summary artifact (`TRUST-1.0.1`)

### P1
3. Local policy sandbox CLI (`TRUST-1.0.2`)
4. Policy simulation mode (shadow evaluation) (`TRUST-1.0.2`)

### P2
5. Compliance evidence generator (`TRUST-1.0.3`)

## ExplainabilitySummaryV1 (proposed schema)

This schema is intentionally composable with the existing 3-file bundle and can be added as a 4th deterministic file without changing replay hash behavior.

```json
{
  "contract_version": "v1",
  "capsule_id": "run-...",
  "tenant_id": "acme-corp",
  "status": "COMMIT",
  "hold": {
    "hold_code": null,
    "hold_reason": null
  },
  "gate_trace": {
    "gate_code": "PASS",
    "duration_ms": 242,
    "failure_reason": null
  },
  "governance_checks": {
    "hash_integrity": { "ok": true },
    "primacy": { "ok": true, "code": "PASS" },
    "mutation_linkage": { "ok": true, "missing": [] }
  },
  "evidence": {
    "persisted_ids": ["ev-123", "ev-456"],
    "mutation_ids": ["mut-abc"],
    "intent_id": "iid-...",
    "proposal_id": "prop-..."
  },
  "lineage": {
    "session_id": "sess-...",
    "scope_lock_id": "slid-...",
    "query_hash": "..."
  }
}
```

## Composition rules

- Source-of-truth remains existing artifacts.
- `ExplainabilitySummaryV1` is a denormalized convenience artifact generated from the same run result object.
- No new TypeDB write path required.
- No hash-key changes in manifest v1/v2.

## Determinism rules

- Stable key ordering in output JSON.
- Lists sorted where available from existing sorted IDs.
- Nulls explicit (avoid omitted-vs-null ambiguity for auditors).

## Promotion path (future)

- Keep explainability fields non-hashed in TRUST-1.0.x.
- If a field becomes an invariant, promote it only in a new manifest version (e.g., v3) and make it required.
