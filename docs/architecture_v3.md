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
- run full pytest suite (currently 395 tests)
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


### OPS-1.2 — Deterministic CI Trust Gates
Status: ✅ COMPLETE
Summary:
- Added deterministic CI gates for `commit` and `hold` outcomes using the trust spine
  (`OntologySteward.run -> governance_gate_node -> integrate_node -> verify_capsule`).
- CI now runs both trust gates after pytest and uploads `ci_artifacts/**` on failure for auditability.
- Gate outputs are deterministic JSON bundles and explicit pass/fail exit codes.

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

Total tests: 401 (current)
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

### Repository Naming Strategy (Git)

To align engineering output with enterprise review workflows, branch + commit naming follows a strict conventional format.

**Repository naming safety checklist (required before push):**
- Branch name must follow `<type>/<short-kebab-topic>` and avoid generic names (`tmp`, `misc`, `work`).
- Commit titles must follow `<type>(<scope>): <subject>` and avoid ambiguous verbs (`update`, `fixes`) without scope.
- PR title should mirror the primary conventional commit subject and explicitly mention the impacted track (`EPI`, `OPS`, `TRUST`) when applicable.
- Merge commit message should preserve milestone traceability (for example: `merge(trust): ... [TRUST-1.0.x/OPS-1.3]`).

- **Commit format**: `<type>(<scope>): <subject>`
  - Examples: `fix(governance): ...`, `docs(trust): ...`, `feat(ops): ...`
- **Allowed primary types**: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `infra`.
- **Scope vocabulary**: reuse canonical tracks/components (`governance`, `trust`, `ops`, `sdk`, `cli`, `docs`, `p16`, `epi`).
- **Branch format**: `<type>/<short-kebab-topic>`
  - Examples: `fix/governance-trust-gates`, `docs/trust-roadmap-sync`.
- **Avoid**: generic branch names (`work`, `tmp`, `misc`) and non-conventional commit titles.

This keeps PR lists machine-filterable and consistent with milestone tracking (`EPI`, `OPS`, `TRUST`).

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
| Operational Spine | CI/CD + migration and deployment safety | OPS 1.x–2.x |
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

#### Milestone B — `EPI-17.0` / `TRUST-1.0.x` / `OPS-1.2` / `OPS-1.3` (LOCKED)
1. **TRUST-1.0 Enterprise SDK (v1)**
   - `GovernedRun` SDK orchestrator implementing strict fail-closed state derivation.
   - `AuditBundleExporter` for deterministic artifact formatting.
   - Audit JSON envelopes include top-level `source_refs` filename pointers.
   - Tenant ID primitive threaded through SDK interfaces and result contracts.
   - Programmatic `verify_capsule` extraction with backward compatibility for legacy envelopes.
2. **TRUST-1.0.1 Explainability Overlay Artifacts**
   - Introduced explainability overlay artifacts as non-hashed exports.
   - Upgraded to `ExplainabilitySummaryV11` (compat alias: `ExplainabilitySummaryV1_1`) with deterministic narratives (`why_commit`, `why_hold`, `blocking_checks`).
3. **TRUST-1.0.2 Policy Sandbox + Simulation (read-only)**
   - Local CLI simulation over exported bundles.
   - Tenant-aware filtering for bundle-only policy evaluation.
4. **TRUST-1.0.3 Compliance Reporting**
   - Bundle-level JSON/CSV compliance reports with percentile metadata, sample-size flags, and stage latency slices.
5. **TRUST-1.0.4 Policy Conflict Detector**
   - Static + dynamic conflict checks with deterministic conflict artifacts and severities.
6. **OPS-1.2 Deterministic CI Trust Gates**
   - Commit + hold deterministic gate runs in CI with exported artifacts.
7. **OPS-1.3 Trust-Gate Trend Summary**
   - Per-run `trust_gate_summary.json` plus concise CI step-summary visibility.
8. **EPI-17.0 Coverage Logging (PLANNED, telemetry-only)**
   - Planned sample event logs with policy label, seed, and bucket tags (`sample_event()`).
   - Planned capsule-level coverage summary metrics (telemetry only, no budget enforcement).

Milestone B closure evidence:
- Deterministic tenant-aware bundle tooling with legacy-safe normalization (`effective_tenant_id`) and nested artifact isolation (`bundle_key`).
- TRUST-1.0.4 conflict detector includes blocking-only code collisions, normalized missing blocking code (`UNSPECIFIED_CODE`), and CI guardrail failure on error severity.
- OPS-1.3 emits deterministic `trust_gate_summary.json`, CI step-summary lines, and offline summary diff utility (`scripts/ops13_trust_gate_diff.py`).
- Versioned artifact schemas are published under `schemas/` for trust summary, policy conflicts, and compliance report contracts.

Milestone B LOCKED rule:
- Any non-backward-compatible artifact contract change requires a `contract_version` bump and a new versioned JSON Schema file under `schemas/`.

#### Milestone C — `TRUST-1.1` / `TRUST-1.2` / `OPS-2.0` / `EPI-17.1` (IN PROGRESS)
1. **TRUST-1.1 Multi-Tenant Foundation & RBAC**
   - Database isolation baseline ACTIVE: `tenant` entity plus ownership relations (`tenant-owns-capsule`, `tenant-owns-intent`).
   - Fail-closed tenant scope checks now gate replay verification/export paths when `tenant_id` is supplied.
   - RBAC primitives (viewer, operator, admin) and broader tenant-scoped APIs (`list_capsules`) remain planned.
2. **TRUST-1.2 Enterprise Control Plane**
   - Fast REST API layer (FastAPI: `/v1/run`, `/v1/capsules`, `/v1/audit/export`).
   - Minimal Web UI (Streamlit/React) for capsule browsing, audit dashboards, and policy editing.
3. **OPS-2.0 Additive Migration Framework**
   - Ordered migration files + migration runner + schema-version tracking.
   - Objective holdout CI suite (frozen regression thresholds).
4. **EPI-17.1 Sampling Budget Enforcement**
   - Budgeted policy mixes only after baseline metrics stabilize.

Milestone C implementation shortlist (high-ROI first):
1. **TRUST-1.1 DB tenant isolation baseline**
   - Introduce `tenant` ownership relations and hard query scoping in Ontology Steward reads/writes.
   - Enforce tenant scope at API boundaries before adding broader RBAC roles.
2. **OPS-2.0 migration safety backbone**
   - Add ordered additive migration runner with schema-version checkpoints and deterministic rollback markers.
   - Gate PRs with migration replay against empty + seeded fixture databases.
3. **TRUST-1.2 minimal control-plane API**
   - Ship `POST /v1/run`, `GET /v1/capsules`, `GET /v1/audit/export` with read-mostly flows and policy hooks.
   - Keep UI out-of-band until API contracts stabilize.
4. **EPI-17.1 coverage telemetry before enforcement**
   - Emit capsule-level coverage metrics and policy-mix traces without budget blocking.
   - Add trend reporting to CI artifacts first; enforce budgets only after variance stabilizes.

### Deliberate Non-Goals (anti-vanity constraints)

- No PKI signature layer in this transition series.
- No swarm-agent expansion.
- No multi-cloud orchestration complexity.
- No heavy confidence math before baseline observability.
- No premature vector retrieval expansion.
- No optional-hashed manifest keys (new integrity fields require a manifest version bump).

### Execution Principle

Trust is produced by enforceable invariants, not claims:
- deterministic mutation identifiers,
- mandatory mutation attribution to capsules,
- replay verifiability,
- policy-enforced hold behavior.
