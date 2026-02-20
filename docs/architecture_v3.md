# SuperHyperion — Architecture v3 (Canonical)

This document is the canonical phased architecture map for SuperHyperion.
It preserves **code-canonical phase numbering**, especially Phase 16.0–16.8.

------------------------------------------------------------
## DESIGN PHILOSOPHY
------------------------------------------------------------

> SuperHyperion optimizes for epistemic integrity and auditability over unconstrained novelty.
> Novel methods are supported via governed operator extension.

### Authority Model

| Role | Authority | Sovereign? |
|------|-----------|------------|
| LLM | Advisory (ideas, designs, proposals) | ❌ |
| Templates | Mechanical (truth-preserving execution) | ❌ |
| Steward | Constitutional (enforces invariants) | ❌ |
| Human | **Sovereign** (identity + belief mutation) | ✅ |

### Two Sovereign Points
1. **Scope Lock** — identity formation (“What are we talking about?”)
2. **Write-Intent** — belief mutation (“What becomes durable truth?”)

------------------------------------------------------------
## EPISTEMIC STAGES (5-Stage Model)
------------------------------------------------------------

| Stage | Phases | Produces | Authority |
|------|--------|----------|-----------|
| EXPLORATION | P1–P5 | scope-draft, speculative-hypothesis | LLM |
| COMMITMENT | ScopeLockGate | scope-lock | Human |
| EXPERIMENTATION | P6–P8 | template-execution, evidence-candidate | Templates |
| ADJUDICATION | P9–P12 + P16.x | proposals, intents | Steward |
| MUTATION | P13–P14 | durable KB updates | Human |

------------------------------------------------------------
## OPS 1.0 — CI/CD OPERATIONAL SPINE (INFRA TRACK)
------------------------------------------------------------

Ops 1.0 is infrastructure. It does not add epistemic capability, but it **enforces**
the invariants by making them merge- and deploy-gated.

### Environments

| Environment | Purpose | TypeDB | Secrets allowed |
|-------------|---------|--------|-----------------|
| dev | local iteration | local Core (docker-compose) | local only |
| ci | deterministic PR gate | ephemeral TypeDB Core service container | NO cloud secrets |
| staging | schema + integration rehearsal | TypeDB Cloud | staging env secrets only |
| prod | real users | TypeDB Cloud | prod env secrets only |

### CI (PR Gate)
Triggered on pull_request.
Enforces:
- boot TypeDB Core service container
- apply schema cleanly to empty DB
- run full pytest suite (currently 365 tests)
- block merge on failure

### CD (Staging Schema Deploy)
Triggered on push to main.
Enforces:
- TLS-capable schema deploy to TypeDB Cloud (staging)
- secrets isolated via GitHub Environment “staging”
- connectivity smoke check after schema apply

### Non-goals (Ops 1.0)
- deploy API/UI containers to cloud
- production rollout automation
- automatic backward-compatible migrations
- load/perf scaling

------------------------------------------------------------
## PHASE 1 — CLAIM INGESTION
------------------------------------------------------------
Status: ✅ COMPLETE

------------------------------------------------------------
## PHASE 2 — CLAIM DECOMPOSITION
------------------------------------------------------------
Status: ✅ COMPLETE

------------------------------------------------------------
## PHASE 3 — PROPOSITION MATERIALIZATION
------------------------------------------------------------
Status: ✅ COMPLETE

------------------------------------------------------------
## PHASE 4 — CONTEXTUAL RETRIEVAL
------------------------------------------------------------
Status: ✅ COMPLETE

------------------------------------------------------------
## PHASE 5 — SPECULATIVE HYPOTHESIS GENERATION
------------------------------------------------------------
Status: ✅ COMPLETE (Phase 11 hardened)

------------------------------------------------------------
## PHASE 6 — EXPERIMENT DESIGN
------------------------------------------------------------
Status: ✅ COMPLETE

------------------------------------------------------------
## PHASE 7 — MONTE CARLO EXECUTION
------------------------------------------------------------
Status: ✅ COMPLETE

------------------------------------------------------------
## PHASE 8 — DIAGNOSTICS & FEYNMAN CHECKS
------------------------------------------------------------
Status: ✅ COMPLETE

------------------------------------------------------------
## PHASE 9 — VALIDATION EVIDENCE CREATION
------------------------------------------------------------
Status: ✅ COMPLETE

------------------------------------------------------------
## PHASE 10 — EPISTEMIC PROPOSALS
------------------------------------------------------------
Status: ✅ COMPLETE

------------------------------------------------------------
## PHASE 11 — SPECULATIVE LANE HARDENING
------------------------------------------------------------
Status: ✅ LOCKED

------------------------------------------------------------
## PHASE 12 — RETRIEVAL QUALITY & META-CRITIQUE
------------------------------------------------------------
Status: ✅ COMPLETE

------------------------------------------------------------
## PHASE 13 — ONTOLOGY STEWARD (FINAL GATEKEEPER)
------------------------------------------------------------
Status: ✅ COMPLETE

------------------------------------------------------------
## PHASE 14 — HUMAN-IN-THE-LOOP (HITL)
------------------------------------------------------------
Status: 🟡 SCAFFOLDED

------------------------------------------------------------
## PHASE 15 — END-TO-END AUDITABLE SYSTEM
------------------------------------------------------------
Status: ✅ READY / VERIFIED

------------------------------------------------------------
## PHASE 16 — PROGRAMMATIC EPISTEMOLOGY (16.0–16.7)
------------------------------------------------------------

### Phase 16 invariants (tighteners)
1. Lane governance via WriteIntent envelope metadata.
2. Constitutional seal applied before evidence minting.
3. Deterministic IDs (evidence, proposals, capsules).
4. Typed channel discipline (validation vs negative semantics).
5. Proposal-only mutation (no direct belief mutation without intent/HITL).

### PHASE 16.0 — Speculation → Experiment Bridge
Status: ✅ COMPLETE

### PHASE 16.1 — Evidence Semantics
Status: ✅ COMPLETE

### PHASE 16.2 — Theory Change Operator & Governance
Status: ✅ COMPLETE

### PHASE 16.3 — Governance Integration (idempotent staging)
Status: ✅ COMPLETE
Summary:
- deterministic proposal_id for dedupe
- staging pipeline integrated with intent service + registry discipline

### PHASE 16.4 — Evidence Normalization & Fail-Closed Integration
Status: ✅ COMPLETE
Summary:
- validator evidence schema normalized to steward insert format
- governance gate introduced and workflow reordered so governance precedes synthesis
- integrator refuses synthesis without governed artifacts

### PHASE 16.5 — Governance Coherence + Ledger Primacy
Status: ✅ COMPLETE
Summary:
- coherence checks: intent exists, proposal match, evidence IDs present, set equality, scope lock match
- ledger primacy verifier prevents chat-trace primacy
- red-team tests enforce HOLD codes on mismatch

### PHASE 16.6 — Run Capsule (Reproducibility)
Status: ✅ COMPLETE
Summary:
- deterministic capsule ID + manifest hash
- snapshot stored (best-effort persistence) + integrity verification path

### PHASE 16.7 — Replay + Eval CLI
Status: ✅ COMPLETE
Summary:
- replay verify: fetch capsule, verify integrity, re-run primacy checks
- eval run: smoke suite with HOLD breakdown + metrics output

### PHASE 16.8 — Reproducibility Auditor (Audit Spine)
Status: ✅ LOCKED
Summary:
- verify_capsule: standalone verification of scientific record integrity
- session_id standardization: deterministic propagation to ensure parity between run and replay
- hardened validation: simulation docstring safety for multi-line claim processing

------------------------------------------------------------
## POST-16.8 RISKS / NEXT EPICS
------------------------------------------------------------

1) Cloud schema drift without CD → addressed by Ops 1.0 staging deploy.
2) Backward compatibility for schema migrations → planned (Ops 2.0).
3) Production deployment + runtime secrets hardening → planned (Ops 2.0).
4) Retrieval plane scaling (vector/hybrid) → deferred until workloads require it.
5) HITL full UI + approval workflows → candidate for Phase 17+ capability track.

------------------------------------------------------------
## TESTING STATUS
------------------------------------------------------------

Total tests: 365 (baseline)
All green: ✅

Core guarantees covered:
- evidence semantics + channel discipline
- governance spine (fail-closed)
- coherence + primacy
- capsule hashing + replay verification
- eval harness

------------------------------------------------------------
## ARCHITECTURE EVOLUTION PLAN — TRUST RUNTIME SERIES
------------------------------------------------------------

This section replaces week-based roadmap labels with an industry-standard release train.
Execution is organized by **tracks + milestones**, not calendar estimates.

### Naming Unification Standard

- **Tracks**
  - `EPI` — epistemic mechanics and verification guarantees.
  - `OPS` — operational reliability and deployment safety.
  - `TRUST` — enterprise control plane and policy governance.
- **Milestone format**: `<TRACK>-<MAJOR>.<MINOR>` (example: `EPI-17.0`).
- **Status labels**: `PLANNED`, `ACTIVE`, `HARDENING`, `LOCKED`.
- **No week-based labels** in architecture planning (no "NOW/NEXT/LATER").

### Track Model

| Track | Scope | Active Series |
|------|-------|---------------|
| Epistemic Core | Truth mechanics, deterministic mutation pipeline | EPI 16.x |
| Audit & Coverage | Objective trust guarantees and replay fidelity | EPI 17.x |
| Operational Spine | CI/CD + migration and deployment safety | OPS 2.x |
| Enterprise Trust Layer | Policy control plane + operator APIs + RBAC | TRUST 1.x |

### Release Train (Ordered)

#### Milestone A — `EPI-16.8` / `OPS-1.1` (LOCKED)
1. **EPI-16.8 Audit Spine Completion**
   - Mutation-event model and capsule linkage as mandatory invariant.
   - Fail-closed governance on missing mutation linkage metadata.
   - Replay verification includes capsule↔mutation linkage completeness.
2. **OPS-1.1 Steward Write Hardening**
   - Deterministic idempotency anchors and structured write-result trail.
   - Deterministic failure semantics for partial/failed durable writes.
3. **EPI-16.8 Contract Freeze v1**
   - Strict typed handoff contracts at critical boundaries.
   - Unknown-field rejection and cross-lane leakage rejection.
4. **OPS-1.1 Operational Guardrails**
   - Canonical gate/hold codes.
   - Node-level duration/failure/gate telemetry in governance artifacts.

Milestone A completion evidence:
- Mutation linkage is fail-closed and replay-verifiable.
- Steward emits deterministic write-result trail (`steward_write_results`).
- Governance output is validated under `contract_version: v1` and includes gate telemetry (`gate_code`, `failure_reason`, `duration_ms`).

#### Milestone B — `EPI-17.0` / `OPS-2.0` / `TRUST-1.0` (HARDENING)
1. **TRUST-1.0 Enterprise SDK (v1)**
   - `GovernedRun` SDK orchestrator implementing strict fail-closed state derivation.
   - Auditable Audit Bundle export (`export_audit_bundle`) with deterministic artifact formatting.
   - Tenant ID primitive threaded through SDK interfaces and result contracts.
   - Programmatic `verify_capsule` extraction with backward compatibility for legacy envelopes.
2. **OPS-2.0 Additive Migration Framework**
   - Ordered migration files + migration runner + schema-version tracking.
   - Additive schema changes only.
3. **EPI-17.0 Coverage Logging**
   - Sample event logs with policy label, seed, and bucket tags.
   - Capsule-level coverage summary metrics.
4. **OPS-2.0 Objective Holdout CI Suite**
   - Frozen holdout scenarios with regression thresholds in CI.

#### Milestone C — `EPI-17.1` / `TRUST-1.1` (PLANNED)
1. **TRUST-1.1 Policy Core (Toggles & Thresholds)**
   - Explicit policy toggles and threshold checks for governance.
   - Deterministic policy evaluation; no DSL in this milestone.
2. **EPI-17.1 Sampling Budget Enforcement**
   - Budgeted policy mixes only after baseline metrics stabilize.
3. **TRUST-1.1 Control Plane + RBAC**
   - `list_capsules`, `list_intents`, `diff_runs`, `export_audit_bundle` (remote/API), `list_policy_violations`.
4. **TRUST-1.1 Reliability Program**
   - Confidence composition and operational SLOs.

### Deliberate Non-Goals (anti-vanity constraints)

- No PKI signature layer in this transition series.
- No swarm-agent expansion.
- No multi-cloud orchestration complexity.
- No heavy confidence math before baseline observability.
- No premature vector retrieval expansion.

### Execution Principle

Trust is produced by enforceable invariants, not claims:
- deterministic mutation identifiers,
- mandatory mutation attribution to capsules,
- replay verifiability,
- policy-enforced hold behavior.
