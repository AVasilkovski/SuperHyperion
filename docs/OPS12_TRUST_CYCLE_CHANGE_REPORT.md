# OPS-1.2 + TRUST-1.0.x Change Report (Follow-up Fixes)

## Why this follow-up was made
This report documents corrective follow-up work applied after review feedback on the previous PR implementation. The goals were:
- preserve deterministic behavior in CI trust gates,
- reduce global side effects in the gate runner,
- keep trust overlays bundle-only and read-only,
- align architecture documentation with implemented runtime behavior.

## 1) OPS-1.2 trust gate hardening

### Files
- `scripts/ops12_ci_trust_gates.py`

### Changes
1. **Deterministic intent seeding**
   - Replaced random `write_intent_service.stage(...)` intent creation with deterministic insertion of a staged intent (`intent-ci-1`, `prop-ci-1`) for the COMMIT gate path.
   - This removes random UUID drift from gate outputs and keeps coherence checks satisfied.

2. **Deterministic service reset**
   - Added reset routine that installs a fresh `InMemoryIntentStore` into the global service for each run to avoid cross-run contamination.

3. **Scoped monkeypatching**
   - Reworked method overrides to use `unittest.mock.patch.object(...)` context managers for steward and integrator read paths.
   - This avoids persistent process-global mutation and makes execution easier to reason about.

4. **Behavior preserved**
   - HOLD gate still validates `NO_EVIDENCE_PERSISTED` and absence of capsule.
   - COMMIT gate still validates STAGED governance + capsule + replay verify PASS.

## 2) Architecture document update

### Files
- `docs/architecture_v3.md`

### Changes
1. Updated test count references from older values to current suite count.
2. Added explicit section for **OPS-1.2** deterministic trust gates.
3. Added explicit sections for:
   - **TRUST-1.0.1** ExplainabilitySummaryV1 overlay,
   - **TRUST-1.0.2** local policy sandbox simulation,
   - **TRUST-1.0.3** bundle-only compliance reporting.

## 3) Validation performed

1. Full repository tests were executed (`pytest tests/ -q`).
2. Gate-specific and TRUST-specific unit tests were validated in prior pass and remain green under full test run.

## 4) Constraint alignment checklist

- No policy DSL introduced (Python callables retained).
- No new TypeDB dependence introduced for TRUST-1.0.1/1.0.2/1.0.3 (bundle-only paths retained).
- Capsule hash invariants untouched; explainability remains a non-hashed overlay artifact.
- Deterministic CI behavior improved by removing random intent IDs from COMMIT gate setup.

## 5) Notes

This follow-up intentionally focused on review-risk areas (determinism and side effects) without broad feature redesign, to keep risk low and preserve compatibility with existing tests and contracts.
