# SuperHyperion — TRUST-1.0 SDK 

The `GovernedRun` SDK is the single enterprise entrypoint. It wraps the canonical v2.1 workflow and guarantees strict fail-closed governance, returning a `GovernedResultV1` envelope. It never bypasses the `OntologySteward` and strictly guarantees auditability.

## Quickstart

```python
import asyncio
from src.sdk import GovernedRun

async def main():
    # 1. Execute a governed run (fail-closed integration)
    result = await GovernedRun.run(
        query="Does compound X inhibit pathway Y?",
        tenant_id="acme-corp"
    )

    # 2. Inspect the enterprise result envelope
    print(f"Status: {result.status}") # "COMMIT" or "HOLD" or "ERROR"
    if result.status == "COMMIT":
        print(f"Capsule ID: {result.capsule_id}")
        print(f"Replay Passed: {result.replay_verdict.status == 'PASS'}")
    else:
        print(f"Hold Reason: [{result.hold_code}] {result.hold_reason}")

    # 3. Export auditable artifacts for reviewers
    artifacts = AuditBundleExporter.export(result, "./audit_logs")
    print(f"Exported artifacts: {artifacts}")

if __name__ == "__main__":
    asyncio.run(main())
```

## Audit Bundle Export
The audit bundle securely creates exactly 3 files, completely deterministically sorted and structurally stable:
1. `<capsule_id>_governance_summary.json`
2. `<capsule_id>_run_capsule_manifest.json`
3. `<capsule_id>_replay_verify_verdict.json`
