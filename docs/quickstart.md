# SuperHyperion: 5-Minute Quickstart

## 1. Setup

Get the environment ready by installing dependencies and configuring your TypeDB connection.

```bash
# Clone and install
git clone https://github.com/AVasilkovski/SuperHyperion.git
cd SuperHyperion
pip install -e .

# Start ephemeral TypeDB core (requires Docker)
docker run -d --name typedb -p 1729:1729 typedb/typedb:3.8.0

# Apply the latest additive schema
export TYPEDB_ADDRESS=localhost:1729
export TYPEDB_DATABASE=superhyperion
python scripts/apply_schema.py --database $TYPEDB_DATABASE
```

## 2. Python SDK

```python
from src.sdk.types import RunCapsuleRequest
from src.hitl.intent_service import write_intent_service

# 1. Stage a reasoning action
intent = write_intent_service.stage(
    intent_type="create_proposition",
    payload={"assertion": "The sky is blue"},
    lane="speculative",
    proposal_id="prop-123"
)

print(f"Staged intent: {intent.intent_id} (Status: {intent.status.value})")

# 2. Accept the execution via governance
write_intent_service.submit_for_review(intent.intent_id)
write_intent_service.approve(intent.intent_id, approver_id="admin", rationale="Looks good")

# 3. Execute
write_intent_service.execute(intent.intent_id, execution_id="exec-456")
```

## 3. Operations & Tenant Isolation API

Run the Control Plane API directly to test isolation semantics.

```bash
# Terminal 1: Start API server
uvicorn src.api.main:app --reload

# Terminal 2: Interact
# Tenant isolation is strictly enforced via X-Tenant-Id
curl -H "X-Tenant-Id: my_tenant_alpha" -H "X-Role: admin" http://localhost:8000/v1/capsules
```

## 4. CI/CD Operations

SuperHyperion includes robust safeguards explicitly to protect the foundational ontology.

- **`scripts/additive_linter.py`**: Validates that new `.tql` commits only *add* capabilities, rejecting destructives (`delete owns`, `delete plays`).
- **`scripts/migrate.py`**: Executes strict, linear forward migrations mapped into a `schema-version` audit trail in TypeDB.
- **Ghost DB Testing**: Verifies multi-tenant latency queries continually track P99 metrics in CI (exported via `ci_artifacts/perf/perf_metrics.json`).
