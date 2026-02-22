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

Total tests: 458 (current)
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

SuperHyperion follows **Conventional Commits** to ensure the codebase history is machine-readable and milestone-traceable.

**Mandatory Format**: `<type>(<scope>): <subject> [<TRACK>-<ID>]`

| Element | Rule | Examples |
|---------|------|----------|
| **Symmetry** | PR Title must reach **identical parity** with the Final Merge/Squash commit. | `fix(ops): stabilize CD pipeline [OPS-1.3]` |
| **Commit Type** | Use only allowed types. No `merge:` or `update:` prefixes. | `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `infra` |
| **Commit Scope**| Components/Tracks. | `governance`, `trust`, `ops`, `sdk`, `p16`, `epi` |
| **Separators** | Use `:` followed by exactly one space after the scope. | `: ` (Do not use `/` or `-` as primary title separators) |
| **Milestone** | Mandatory suffix tracking the release series. | `[OPS-1.3]`, `[EPI-17.0]`, `[TRUST-1.0.x]` |

**Repository naming safety checklist (required before push):**
- **Branch Naming**: Follow `<type>/<short-kebab-topic>`. Use `/` only to separate type from topic (e.g., `fix/typedb-deployment`).
- **Semantic Integrity**: titles must remain semantic to support automated changelogs. Never start a PR or commit title with `merge:`.
- **Pre-Push Scan**: Check for sensitive artifacts (`.env`, `.gemini`) before committing to a remote.

**Avoid**: generic branch names (`work`, `tmp`, `misc`) and non-conventional commit titles.

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
   - Gate runner performs explicit TypeDB readiness probing: CI remains fail-closed; local runs may emit deterministic `SKIP` when DB is unavailable.
7. **OPS-1.3 TypeDB Cloud Schema Deploy Stabilization (✅ COMPLETE)**
   - **Self-Healing**: Automated SVL42 auto-migration engine (noise suppressed via inherited capability scrubbing).
   - **Fail-Fast**: Hardcoded canonical paths + pre-flight workflow assertions (`set -euo pipefail`, `test -f`, wildcard guards).
   - **Observability**: Dry-run auditing supported without functional TypeDB driver DLLs; prints argv + resolved schema file list for provenance.
   - **Naming Safety**: Implementation of Repository Naming Safety Checklist for PR/Merge parity.
8. **OPS-1.4 Trust-Gate Trend Summary**
   - Per-run `trust_gate_summary.json` plus concise CI step-summary visibility.
9. **EPI-17.0 Coverage Logging (PLANNED, telemetry-only)**
   - Planned sample event logs with policy label, seed, and bucket tags (`sample_event()`).
   - Planned capsule-level coverage summary metrics (telemetry only, no budget enforcement).

Milestone B closure evidence:
- Deterministic tenant-aware bundle tooling with legacy-safe normalization (`effective_tenant_id`) and nested artifact isolation (`bundle_key`).
- TRUST-1.0.4 conflict detector includes blocking-only code collisions, normalized missing blocking code (`UNSPECIFIED_CODE`), and CI guardrail failure on error severity.
- OPS-1.3/OPS-1.4: Emits deterministic `trust_gate_summary.json` and supports **Self-Healing Schema CD**.
- Versioned artifact schemas are published under `schemas/` for trust summary, policy conflicts, and compliance report contracts.

Milestone B LOCKED rule:
- Any non-backward-compatible artifact contract change requires a `contract_version` bump and a new versioned JSON Schema file under `schemas/`.

#### Milestone C — `TRUST-1.1` / `TRUST-1.2` / `OPS-2.0` / `EPI-17.1` (LOCKED)
1. **OPS-2.0 Enterprise Migration Framework (✅ COMPLETE)**
   - **Linearity**: Ordered `migrations/NNN_topic.tql` path for explicit state progression.
     - `001_init`: core bootstrap (schema_version, tenant, tenancy roles).
     - `002_minimal_types`: domain labels to resolve `[SYR1]` type-not-found errors.
     - `003_role_attachment`: Attach `plays` constraints to validated types.
   - **Versioning**: Mandatory `schema-version` entity in TypeDB (attributes: `ordinal`, `git-commit`, `applied-at`).
   - **N-1 Strategy**: Enforcement of additive-only schema changes via `additive_linter.py`.
   - **Health Check**: TypeDB 3.8 compatible `schema_health.py` resolving ordinals from migration history; elimination of `SessionType` legacy imports.
   - **Immutability**: Hardened `SCHEMA_FILE` guards in CI/CD blocks (mandatory `unset`, double-bracket wildcard rejection, `test -f` fatal checks).
   - **Perf Safety**: "Ghost DB" automated benchmark (10k entities) for P99 latency tracking.
   - **CI Enforced**:
     - `additive_linter.py` in PR CI prevents destructive changes.
     - Migrate dry-run and ephemeral apply validation in PR CI.
     - `schema_health.py` parity gate in CI and staging CD.
2. **TRUST-1.1 Multi-Tenant Foundation & RBAC (✅ COMPLETE)**
   - Database isolation baseline: `tenant` entity plus ownership relations (`tenant-owns-capsule`, etc.).
   - **Tenant Scope Helper**: `tenant_scope.py` injection for hard query scoping in Steward.
   - Fail-closed tenant checks gate replay verification/export paths when `tenant_id` is supplied.
3. **TRUST-1.2 Enterprise Control Plane (✅ COMPLETE)**
   - Minimal FastAPI endpoints: `POST /v1/run`, `GET /v1/capsules`, `GET /v1/audit/export`.
   - Tenant-scoping at the API boundary (fail-closed, returning 404 for tenant mismatch to prevent enumeration).
   - Basic RBAC: `POST /v1/run` requires `operator`/`admin`; `GET` endpoints allow `viewer`.
   - **TRUST-1.2.1 Auth Context Binding (✅ HARDENING/COMPLETE)**: 
     - Supported JWT claims: `tenant_id` or `tid`, `role`, `sub`, `exp`, optional `iss`/`aud`.
     - **Explicit requirement:** header auth is dev-only triple-gated. Production requires JWT-bound AuthContext.
   - **Explicit Non-Goals**: No persistent job store, no RBAC UI, no policy DSL editing UI, no JWKS/OIDC discovery.
4. **EPI-17.1 Telemetry before enforcement (PLANNED)**
   - Capsule-level coverage metrics and CI artifact trends.
   - Trend reporting to CI artifacts; budgets enforced only after variance stabilizes.

------------------------------------------------------------
## RISK REGISTER (Milestone C)
------------------------------------------------------------

| Risk ID | Description | Likelihood | Impact | Detection | Mitigation | Rollback Plan |
|---|---|---|---|---|---|---|
| REQ-01 | **Tenant Isolation Leak**: Cross-tenant data leakage. | Low | High | Unit & Acceptance tests querying cross-tenant resources. | Use `tenant_scope.py` injection helper; default fail-closed. | Revert API deployment, reset DB tenant mappings manually. |
| REQ-02 | **Migration Correctness**: `schema-version` drift or partial apply. | Med | High | Pre-flight linear version checks in `migrate.py` + `schema_health.py`. | Atomic `TypeDB.transaction` wrapping version increments. | Restore from TypeDB Cloud backup snapshot. |
| REQ-03 | **Drift Guard Masking**: Auto-migrate hides migration accountability. | Med | Med | Code review and Linter tracking `undefine` execution. | Restrict guard scope to inherited capability scrubbing (SVL42). | Fast-forward fix commit restricting `apply_schema.py` scope. |
| REQ-04 | **Cloud Operations**: TLS/CA issues or Schema Tx aborts. | Low | High | CI connectivity smoke tests and CD dry-runs. | Retries implemented in `migrate.py`; driver cert hardening. | Rollback CI/CD runner environments; bypass TLS temporary locally. |
| REQ-05 | **Performance Regression**: Added tenant checks slow down P99 latency. | Med | Med | "Ghost DB" automated benchmark run in CI PR gate. | Indexed ownership lookups; 10k entity baseline gates. | Disable tenant enforcement temporarily or revert. |
| REQ-06 | **Observability Gaps**: Missing logging for tenant-scoped failures. | Low | Med | Lack of structured logs. | FastAPI Dependency injection ensures all `tenant_id` scopes are logged. | Hotfix adding middleware loggers. |
| REQ-07 | **Overengineering**: Too many moving parts block launch. | High | Med | PR cycle times increase; team velocity drops. | Choose smallest architectural footprint that satisfies safety. | Cut scope directly; merge strictly required safety first. |

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
