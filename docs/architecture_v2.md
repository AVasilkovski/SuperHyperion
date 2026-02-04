# SuperHyperion — Master Task & Architecture Map

This document defines the canonical phased architecture of SuperHyperion.
Each phase introduces strictly bounded capabilities with explicit epistemic guarantees.

------------------------------------------------------------
## DESIGN PHILOSOPHY
------------------------------------------------------------

> **SuperHyperion optimizes for epistemic integrity and auditability over unconstrained novelty. Novel methods are supported via governed operator extension.**

### Authority Model

| Role | Authority | Sovereign? |
|------|-----------|------------|
| LLM | Advisory (ideas, designs, proposals) | ❌ |
| Templates | Mechanical (truth-preserving execution) | ❌ |
| Steward | Constitutional (enforces invariants) | ❌ |
| Human | **Sovereign** (identity + belief mutation) | ✅ |

### Two Sovereign Points

1. **Scope Lock** — Identity formation ("What are we talking about?")
2. **Write-Intent** — Belief mutation ("What becomes durable truth?")

------------------------------------------------------------
## EPISTEMIC STAGES (5-Stage Model)
------------------------------------------------------------

| Stage | Phases | Produces | Authority |
|-------|--------|----------|-----------|
| **EXPLORATION** | P1–P5 | scope-draft, speculative-hypothesis | LLM |
| **COMMITMENT** | ScopeLockGate | scope-lock | **Human** |
| **EXPERIMENTATION** | P6–P8 | template-execution, evidence-candidate | Templates |
| **ADJUDICATION** | P9–P12 | epistemic-proposal, write-intent(staged) | Steward |
| **MUTATION** | P13–P14 | durable KB updates | **Human** |


------------------------------------------------------------
## PHASE 1 — CLAIM INGESTION
------------------------------------------------------------
**Goal:**
- Accept raw user input (text, documents, datasets)
- Normalize into machine-tractable text

**Key Outputs:**
- Raw text corpus
- Source metadata

**Constraints:**
- No interpretation
- No claims inferred

**Status:** ✅ COMPLETE

------------------------------------------------------------
## PHASE 2 — CLAIM DECOMPOSITION
------------------------------------------------------------
**Goal:**
- Decompose text into atomic scientific claims

**Key Outputs:**
- `atomic_claims[]`
  - `claim_id` (stable)
  - `content`
  - `subject` / `relation` / `object` (if extractable)

**Constraints:**
- Claims must be minimal and testable
- `claim_id` becomes the global anchor

**Status:** ✅ COMPLETE

------------------------------------------------------------
## PHASE 3 — PROPOSITION MATERIALIZATION
------------------------------------------------------------
**Goal:**
- Convert atomic claims into TypeDB propositions

**Key Outputs:**
- `proposition` entities
  - `entity-id` = `claim_id`
  - `content`
  - initial `epistemic-status` = "unresolved"

**Constraints:**
- One proposition per `claim_id`
- No evidence attached yet

**Status:** ✅ COMPLETE

------------------------------------------------------------
## PHASE 4 — CONTEXTUAL RETRIEVAL
------------------------------------------------------------
**Goal:**
- Retrieve prior knowledge, papers, datasets, references

**Key Outputs:**
- Retrieved documents
- Source candidates

**Constraints:**
- Retrieval is advisory only
- No belief updates

**Status:** ✅ COMPLETE

------------------------------------------------------------
## PHASE 5 — SPECULATIVE HYPOTHESIS GENERATION (SPECULATIVE LANE)
------------------------------------------------------------
**Goal:**
- Generate alternative explanations, analogies, edge cases

**Key Outputs:**
- `speculative_context[claim_id]`
- `speculative-hypothesis` entities (session-scoped)

**Constraints:**
- MUST NOT update beliefs
- MUST NOT generate evidence
- MUST be labeled `epistemic_status = "speculative"`

**Tests:**
| Test | Assertion |
|------|-----------|
| `test_p11_speculative_persistence_segregation` | Speculative entities isolated |
| `test_v22_p11_speculative_happy_path_with_proposition` | Session link created |
| `test_v22_p11_speculative_segregation` | No evidence from speculative |

**Status:** ✅ COMPLETE (Phase 11 hardened)

------------------------------------------------------------
## PHASE 6 — EXPERIMENT DESIGN
------------------------------------------------------------
**Goal:**
- Design verification experiments for each claim

**Key Outputs:**
- `ExperimentSpec`
  - `claim_id`
  - `hypothesis`
  - `template_id`
  - `parameters`
  - `assumptions`

**Constraints:**
- Only vetted templates allowed
- Design may be informed by prior steps, but produces no evidence

**Tests:**
| Test | Assertion |
|------|-----------|
| `test_registry_has_all_experiment_spec_templates` | All templates registered |

**Status:** ✅ COMPLETE

------------------------------------------------------------
## PHASE 7 — MONTE CARLO EXECUTION
------------------------------------------------------------
**Goal:**
- Execute experiments deterministically

**Key Outputs:**
- Execution results
- Raw numerical outcomes

**Constraints:**
- No interpretation
- No belief updates

**Tests:**
| Test | Assertion |
|------|-----------|
| `test_v22_hardening.py::test_determinism` | Reproducible results |
| `test_p13_verify_pipeline_happy_path` | Pipeline completes |

**Status:** ✅ COMPLETE

------------------------------------------------------------
## PHASE 8 — DIAGNOSTICS & FEYNMAN CHECKS
------------------------------------------------------------
**Goal:**
- Verify experiment health and validity

**Checks:**
- Dimensional consistency
- Statistical diagnostics (ESS, variance)
- Sensitivity / fragility analysis

**Key Outputs:**
- `diagnostics` report
- `fragility` flags

**Constraints:**
- Fragile results cannot be marked PROVEN

**Tests:**
| Test | Assertion |
|------|-----------|
| `test_p13_verify_fragility_detection` | Fragility detected |
| `test_p13_verify_diagnostic_failure` | Bad diagnostics caught |
| `test_template_param_bounds` | Param bounds enforced |

**Status:** ✅ COMPLETE

------------------------------------------------------------
## PHASE 9 — VALIDATION EVIDENCE CREATION
------------------------------------------------------------
**Goal:**
- Create grounded validation evidence from successful experiments

**Key Outputs:**
- `validation-evidence` entities
  - `claim_id`
  - `execution_id`
  - `success`
  - `confidence_score`
  - `audit_payload`

**Constraints:**
- MUST have `claim_id`
- MUST NOT contain speculative markers
- Guarded by `OntologySteward`

**Tests:**
| Test | Assertion |
|------|-----------|
| `test_v22_p11_guard_speculative_evidence` | Speculative rejected |
| `test_v22_p11_guard_missing_claim_id` | claim_id required |
| `test_evidence_contract` | Evidence schema valid |

**Status:** ✅ COMPLETE

------------------------------------------------------------
## PHASE 10 — EPISTEMIC PROPOSALS
------------------------------------------------------------
**Goal:**
- Propose belief updates based on evidence

**Key Outputs:**
- `epistemic-proposal` entities
  - `proposed-status`
  - `confidence`
  - `cap-reasons`

**Constraints:**
- Proposals do NOT mutate beliefs
- Capped by fragility rules

**Tests:**
| Test | Assertion |
|------|-----------|
| `test_cap_enforcement_logic` | Caps enforced |
| `test_v22_e2e_verify_to_steward_happy` | Proposal created |

**Status:** ✅ COMPLETE

------------------------------------------------------------
## PHASE 11 — SPECULATIVE LANE HARDENING
------------------------------------------------------------
**Goal:**
- Enforce an epistemic firewall between speculative and grounded lanes

**Key Changes:**
- `speculative-hypothesis` as standalone entity
- Session-scoped speculative persistence
- Recursive speculative guards
- JSON-string bypass closure
- `claim_id` invariant enforced

**Constraints:**
- No speculative → evidence path exists
- Violations cause hard failure

**Tests:**
| Test | Assertion |
|------|-----------|
| `test_v22_p11_guard_json_string_speculative` | JSON bypass closed |
| `test_v22_p11_guard_json_string_kebab_speculative` | Kebab-case bypass closed |
| `test_v22_p11_guard_nested_speculative` | Nested speculative caught |
| `test_v22_p11_missing_claim_id_does_not_fallback_to_entity_id` | No entity_id fallback |

**Status:** ✅ LOCKED

------------------------------------------------------------
## PHASE 12 — RETRIEVAL QUALITY & META-CRITIQUE
------------------------------------------------------------
**Goal:**
- Persist retrieval quality and verification critique

**Key Outputs:**
- `retrieval-assessment`
- `meta-critique-report`

**Metrics:**
- `coverage`
- `provenance-score`
- `conflict-density`
- `reground-attempts`

**Tests:**
| Test | Assertion |
|------|-----------|
| `test_meta_critique_insert_generation` | Critique persisted |

**Status:** ✅ COMPLETE

------------------------------------------------------------
## PHASE 13 — ONTOLOGY STEWARD (FINAL GATEKEEPER)
------------------------------------------------------------
**Goal:**
- Centralize all persistence and belief mutation

**Responsibilities:**
- Persist all artifacts
- Enforce epistemic invariants
- Execute approved write-intents
- Maintain full audit trail

**Constraints:**
- Only Steward can mutate TypeDB
- Separate delete/insert semantics enforced

**Tests:**
| Test | Assertion |
|------|-----------|
| `test_persist_session_traces` | Traces persisted |
| `test_persist_execution` | Execution persisted |
| `test_persist_proposal` | Proposal persisted |
| `test_execute_intent` | Intent executed |
| `test_write_template_permissions` | Permissions enforced |

**Status:** ✅ COMPLETE

------------------------------------------------------------
## PHASE 14 — HUMAN-IN-THE-LOOP (HITL)
------------------------------------------------------------
**Goal:**
- Allow controlled human approval of belief updates

**Key Outputs:**
- `write-intent`
- `hitl-decision`
- `intent-status-event`

**Constraints:**
- No silent auto-approval
- All decisions auditable

**Tests:**
| Test | Assertion |
|------|-----------|
| `test_intent_status_payload` | Intent status valid |

**Status:** 🟡 SCAFFOLDED

------------------------------------------------------------
## PHASE 15 — END-TO-END AUDITABLE SYSTEM
------------------------------------------------------------
**Goal:**
- Full traceability from question → belief update

**Guarantees:**
- Deterministic persistence
- Reproducible experiments
- Epistemic firewall enforced by code + schema + tests
- No hidden belief mutation paths

**Tests:**
| Test | Assertion |
|------|-----------|
| `test_v22_end_to_end_persistence` | Full flow works |
| `test_v22_e2e_budget_exceeded` | Budget limits honored |
| `test_v22_e2e_diagnostic_failure` | Diagnostic failures handled |

**Status:** ✅ READY / VERIFIED

------------------------------------------------------------
## PHASE 15.1 — CI/CD INFRASTRUCTURE
------------------------------------------------------------
**Goal:**
- Automated testing and validation in CI pipeline

**Key Components:**
- GitHub Actions workflow
- TypeDB Docker container for schema validation
- Automated test execution on PR/push
- Schema syntax verification

**Constraints:**
- All Phase 11+ guards must pass in CI
- No merge without green tests

**Known Infrastructure Issues:**
- `test_schema_static_verification`: Requires `schema_v22_patch.tql` file
- `test_schema_syntax_and_load`: Requires TypeDB Docker setup

**Status:** 🔴 NOT IMPLEMENTED

**Next Steps:**
1. Create `.github/workflows/ci.yml`
2. Add TypeDB Docker service
3. Create missing schema files or fix paths

------------------------------------------------------------
------------------------------------------------------------
## PHASE 16 — PROGRAMMATIC EPISTEMOLOGY (16.0–16.5)
------------------------------------------------------------
> **Evolution Note:** Originally "Brainstorm Bridge", this phase expanded into the core epistemic governance layer (Evidence, Theory, Reproducibility).

### PHASE 16 INVARIANTS (The "5 Tighteners")
1. **Lane Governance**: Enforced in `WriteIntent` envelope (not payload).
2. **Constitutional Seal**: Applied to all evidence before minting.
3. **Deterministic IDs**: Evidence IDs derived from content hash (no `nev-` prefix logic).
4. **Typed Channel Discipline**: Validation=Success, Negative=Failure (enforced by schema).
5. **Proposal-Only Mutation**: All theory changes require HITL `write-intent` (no direct writes).

### REMAINING RISKS (Pre-16.4/16.5)
* **Retrieval Drift**: No snapshot capsule yet (re-runs may differ).
* **Sequential Inserts**: No transactional batcher (potential partial failures).
* **Blind Spots**: No evaluation harness for calibration/oscillation.

### PHASE 16.0 — BRAINSTORM → MC DESIGN BRIDGE
**Goal:**
- Formalize the typed interface between speculative hypothesis generation and experiment design

**Architecture:**
```
SpeculativeAgent           ExperimentHints           VerifyAgent
(speculative lane)  ──────► (context-only)  ──────►  (grounded lane)
                            ├── digest()              │
                            └── epistemic_status      ExperimentSpec
                                ="speculative"        (no residue)
```

**Key Components:**

| Component | Location | Purpose |
|-----------|----------|---------|
| `ExperimentHints` | `src/montecarlo/types.py` | Typed bridge object with `digest()` |
| `PriorSuggestion` | `src/montecarlo/types.py` | Tight typing for analogy priors |
| `_extract_experiment_hints()` | `src/agents/speculative_agent.py` | Converts speculation → hints |
| `_design_experiment_spec()` | `src/agents/verify_agent.py` | Consumes hints for design |

**Invariants:**
1. `experiment_hints` is CONTEXT-ONLY — never persisted to TypeDB
2. Only `digest()` appears in audit trail — not raw speculative content
3. `ExperimentSpec` rejects speculative residue at validation time
4. Steward guard catches any leakage as backup

**Tests:**
| Test | Assertion |
|------|-----------|
| `test_experiment_hints_type_creation` | Hints created with tight typing |
| `test_experiment_hints_digest_is_stable` | Digest reproducible |
| `test_experiment_spec_rejects_experiment_hints_field` | No residue top-level |
| `test_experiment_spec_rejects_speculative_context_field` | No speculative_context |
| `test_steward_rejects_experiment_hints_in_evidence_via_epistemic_status` | Steward catches |

**Status:** ✅ COMPLETE

---

### PHASE 16.1 — EVIDENCE SEMANTICS
**Goal:** Make evidence meaning explicit, typed, and governable.

**Key Additions:**
* `evidence` supertype with `validation-evidence` and `negative-evidence`
* Typed `evidence-role` (support / refute / undercut / replicate)
* Failure modes and refutation strength
* Deterministic evidence IDs + constitutional seal
* Channel discipline (no support in negative lane)

**Status:** ✅ COMPLETE
**Enforced by:** schema + steward guards + 40+ tests

---

### PHASE 16.2 — THEORY CHANGE OPERATOR & GOVERNANCE
**Goal:** Deterministic, reviewable theory updates.

**Key Components:**
* `theory_change_operator.py`
* Deterministic action selection: REVISE / FORK / QUARANTINE / HOLD
* Proposal-only mode (no direct mutation)
* Normative `intent_registry.py`
* Lane governance moved to WriteIntent envelope

**Status:** ✅ COMPLETE

---

### PHASE 16.3 — END-TO-END INTEGRATION (CURRENT)
**Goal:** Make theory change operationally safe and repeatable.

**In Progress:**
* Deterministic `proposal-id` for idempotency
* Session-level observability
* Contract integration test (DB → proposal → intent)

**Status:** 🟡 IN PROGRESS

---

### PHASE 16.4 — REPRODUCIBILITY CAPSULE (PLANNED)
**Goal:** Eliminate retrieval-induced epistemic drift.

**Planned:**
* Retrieval snapshot digests
* Replayable runs
* Capsule integrity checks

**Status:** 🔴 NOT STARTED

---

### PHASE 16.5 — EVALUATION HARNESS (PLANNED)
**Goal:** Make epistemic quality measurable.

**Planned Metrics:**
* Drift rate
* Oscillation frequency
* Calibration (Brier / log loss)
* Governance latency

**Status:** 🔴 NOT STARTED

------------------------------------------------------------
## TEST PHASE ALIGNMENT SUMMARY
------------------------------------------------------------

| Phase | Test File(s) | Count |
|-------|--------------|-------|
| 5 | `test_v22_p11_speculative_*.py` | 7 |
| 6 | `test_v22_p13_verify.py` | 2 |
| 7-8 | `test_v22_hardening.py`, `test_v22_p13_verify.py` | 8 |
| 9 | `test_v22_steward.py` | 8 |
| 10 | `test_v22_e2e.py` | 3 |
| 11 | `test_v22_p11_*.py`, `test_v22_steward.py` | 11 |
| 12 | `test_v22_schema_validation.py` | 1 |
| 13 | `test_v22_steward.py` | 4 |
| 14 | `test_v22_final_sanity.py` | 1 |
| 15 | `test_v22_e2e.py`, `test_v22_integration.py` | 4 |
| 16 | `test_brainstorm_bridge.py` | 14 |

**Total Phase-Aligned Tests:** 63

------------------------------------------------------------

> **This architecture is enforced by code, not by trust.**
>
> Any violation of phase invariants causes a hard failure at persistence time.
