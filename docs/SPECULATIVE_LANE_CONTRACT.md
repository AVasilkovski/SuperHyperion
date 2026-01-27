# Speculative Lane Contract

> **Epistemic Firewall: Formal Specification**
>
> This document defines the invariants that govern the separation between the **Speculative Lane** (hypothesis generation) and the **Grounded Lane** (belief mutation) in SuperHyperion v2.2.

---

## Glossary

| Term | Definition |
|------|------------|
| **Claim ID** | Stable identifier used across decomposition, proposition entity-id, and evidence linking |
| **Proposition** | TypeDB entity representing a scientifically testable claim |
| **Speculative Hypothesis** | Alternative explanation artifact, session-scoped, cannot update beliefs |
| **Validation Evidence** | TypeDB entity linking successful MC execution to a proposition |
| **Truth Assertion** | Cached belief relation (if used); derived from grounded evidence only |
| **Epistemic Status** | 5-state classification: `proven`, `supported`, `unresolved`, `speculative`, `refuted` |

---

## A. Lane Definitions

| Lane | Purpose | Can Mutate Beliefs? |
|------|---------|---------------------|
| **Speculative** | Generate alternative hypotheses, analogies, edge cases | ❌ No |
| **Grounded** | Validate claims via Monte Carlo, update epistemic status | ✅ Yes |

### Core Invariant

> **No implicit promotion.**
>
> A speculative artifact CANNOT become grounded evidence without explicit re-verification through the Monte Carlo pipeline.

---

## B. Allowed / Forbidden Flows

| Artifact | Speculative → Grounded | Enforced Where |
|----------|------------------------|----------------|
| `speculative-hypothesis` | ❌ Forbidden | Schema (no `plays evidence-for-proposition`) + Steward guard |
| `validation-evidence` | ❌ Forbidden | `q_insert_validation_evidence` recursive speculative check |
| `epistemic-proposal` | ❌ Forbidden | `VerifyAgent` output validation |
| `experiment-spec` | ✅ Allowed (inform only) | `VerifyAgent.mc_design()` — speculative informs priors |
| `truth-assertion` | ❌ Forbidden as effect of speculative inputs | Steward policy + schema (no role for `speculative-hypothesis`) |

### Inform vs Persist

- **Inform**: Speculative outputs may be used in **prompting** `VerifyAgent` to design experiments (priors, edge cases, sensitivity parameters).
- **Persist**: Speculative outputs may only enter TypeDB as `speculative-hypothesis` entities (session-scoped). They **never** become `validation-evidence`.

---

## C. Brainstorm → MC Design Bridge

> **The legal crossing point between speculative ideas and grounded tests.**

The bridge formalizes how speculative outputs inform experiment design without violating the firewall.

### Architecture

```
SpeculativeAgent           ExperimentHints           VerifyAgent
(speculative lane)  ──────► (context-only)  ──────►  (grounded lane)
                            ├── digest()              │
                            └── epistemic_status      ExperimentSpec
                                ="speculative"        (no residue)
```

### `ExperimentHints` Type

**Location**: `src/montecarlo/types.py`

```python
class ExperimentHints(BaseModel):
    claim_id: str
    candidate_mechanisms: List[str]      # From alternatives
    discriminative_predictions: List[str] # Testable predictions
    sensitivity_axes: List[str]          # From edge_cases
    prior_suggestions: List[PriorSuggestion]  # From analogies
    falsification_criteria: List[str]
    epistemic_status: Literal["speculative"] = "speculative"  # Guard marker
    
    def digest(self) -> str:  # For audit trail (not raw content)
```

### Invariants

1. **Context-Only**: `experiment_hints` is NEVER persisted to TypeDB
2. **Digest in Audit Trail**: Only the `digest()` appears in traces, not raw content
3. **No Residue in ExperimentSpec**: `ExperimentSpec` model_validator rejects any speculative fields
4. **Steward Guard Backup**: If hints leak to evidence, the `is_speculative()` guard catches it

### No-Residue Validation

**Location**: `src/montecarlo/types.py` → `ExperimentSpec`

```python
SPECULATIVE_RESIDUE_FIELDS = {
    "experiment_hints", "speculative_context", "epistemic_status",
    "alternatives", "analogies", "edge_cases"
}

@model_validator(mode="before")
def reject_speculative_residue(cls, data):
    # Recursive check for forbidden fields at any depth
```

---

## D. Boundary Owners

| Boundary | Owner | Enforced By |
|----------|-------|-------------|
| Speculative → Design | `VerifyAgent` | `ExperimentHints` consumption + no-residue validation |
| Design → Execution | `TemplateRegistry` | Param schema + output schema |
| Execution → Persistence | `OntologySteward` | Guards + query builders |
| Persistence → Mutation | `OntologySteward` | Write-intent approval |

---

## E. Mandatory Guards

### Guard 1: Recursive Speculative Detection (with JSON String Scanning)

**Location**: `src/agents/ontology_steward.py` → `q_insert_validation_evidence`

**Key invariants**:
- Handles both snake_case and kebab-case keys to prevent drift
- **Scans JSON strings** to close bypass vector (speculative markers hidden in serialized payloads)

```python
SPEC_KEYS = {"epistemic_status", "epistemic-status"}
SPEC_CONTEXT_KEYS = {"speculative_context", "speculative-context"}

def is_speculative(obj):
    # --- Critical bypass closure: scan JSON strings too ---
    if isinstance(obj, str):
        s = obj.strip()
        # Try parse JSON-looking strings
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            try:
                return is_speculative(json.loads(s))
            except Exception:
                pass
        # Last-resort tripwire (case-insensitive)
        s_lower = s.lower()
        return (
            '"speculative"' in s_lower
            or '"epistemic_status"' in s_lower
            or '"epistemic-status"' in s_lower
            or '"speculative_context"' in s_lower
            or '"speculative-context"' in s_lower
        )

    if isinstance(obj, dict):
        for k in SPEC_KEYS:
            if obj.get(k) == "speculative":
                return True
        if any(k in obj for k in SPEC_CONTEXT_KEYS):
            return True
        return any(is_speculative(v) for v in obj.values())

    if isinstance(obj, list):
        return any(is_speculative(v) for v in obj)

    return False

if is_speculative(ev):
    raise ValueError("CRITICAL: Attempted to persist speculative evidence!")
```

---

### Guard 2: `claim_id` Non-Null Invariant (No `entity_id` Fallback)

**Location**: `src/agents/ontology_steward.py`

```python
# IMPORTANT: do NOT fall back to ev["entity_id"] (that's typically evidence id, not claim id)
claim_id = ev.get("claim_id") or ev.get("claim-id") or ev.get("proposition_id") or ""

if not claim_id:
    raise ValueError("CRITICAL: Validation evidence missing claim_id!")
```

**Invariants**:
- Validation evidence MUST be linked to a grounded claim. Anonymous evidence is forbidden.
- `entity_id` is **never** used as a fallback for `claim_id` — this prevents evidence from "accidentally" anchoring to itself.

---

### Guard 3: Write-Intent Role Restriction

**Location**: `src/agents/ontology_steward.py`

**Invariant**: Only `OntologySteward` may execute write intents. No agent may directly mutate TypeDB outside the Steward's persistence loop.

---

### Guard 4: Session-Scoped Speculative Isolation

**Location**: `q_insert_speculative_hypothesis`

```typeql
(session: $s, hypothesis: $h) isa session-has-speculative-hypothesis;
```

**Invariant**: Speculative hypotheses are scoped to a session. They cannot be queried as global evidence.

---

## E. Failure Mode Semantics

| Mode | Behavior | Example |
|------|----------|---------|
| **Hard Fail** | Persistence aborted for artifact; session may mark failed | Speculative evidence injection → `ValueError` |
| **Soft Fail** | Best-effort operation; failure is silent but logged | Proposition link missing → hypothesis still persists |

---

## F. Schema-Level Constraints

### Why `speculative-hypothesis` is an Entity (Not a Relation)

1. **Naming collision avoidance**: TypeDB already has `relation hypothesis` for v2.1 Bayesian hypothesis tracking.
2. **First-class queryability**: Entities can own arbitrary attributes (`json`, `confidence-score`, etc.).
3. **Clear segregation**: Entities cannot accidentally participate in grounded relations unless explicitly declared.

---

### Why `speculative-hypothesis` Cannot Play `evidence-for-proposition`

The schema defines:

```typeql
relation evidence-for-proposition,
  relates evidence,
  relates proposition;

validation-evidence plays evidence-for-proposition:evidence;
```

`speculative-hypothesis` is **not listed** as playing the `evidence` role. This is enforced by schema structure.

---

### Epistemic Status Promotion Policy

`epistemic-status = "speculative"` has **no direct promotion path**.

Promotion requires:
1. **Validation evidence**: `success: true` from MC execution
2. **Non-fragile checks**: Feynman checks passed, no sensitivity failures
3. **Steward-approved write intent**: Human-in-the-loop approval if required

There is no shortcut. The database structure alone does not prevent status updates; **policy enforcement** is required at the Steward layer.

---

## G. Test-to-Invariant Traceability Matrix

| Invariant | Test Name | Assertion |
|-----------|-----------|-----------
| No speculative → evidence | `test_v22_p11_guard_speculative_evidence` | `ValueError` raised |
| No nested speculative | `test_v22_p11_guard_nested_speculative` | `ValueError` raised |
| **No JSON string bypass** | `test_v22_p11_guard_json_string_speculative` | `ValueError` raised |
| **Kebab-case JSON bypass** | `test_v22_p11_guard_json_string_kebab_speculative` | `ValueError` raised |
| claim_id required | `test_v22_p11_guard_missing_claim_id` | `ValueError` raised |
| **No entity_id fallback** | `test_v22_p11_missing_claim_id_does_not_fallback_to_entity_id` | `ValueError` raised |
| **kebab claim-id accepted** | `test_v22_p11_claim_id_kebab_case_accepted` | Query contains `claim-id` |
| Session link created | `test_v22_p11_speculative_happy_path_with_proposition` | `len(links) == 2` |
| Proposition link conditional | `test_v22_p11_speculative_no_proposition_no_link` | `created == 0`, `attempted == 1` |
| No evidence from speculative | `test_v22_p11_speculative_segregation` | `len(validation-evidence) == 0` |
| **Bridge: Hints have digest** | `test_experiment_hints_digest_is_stable` | Digests match for same content |
| **Bridge: No residue top-level** | `test_experiment_spec_rejects_experiment_hints_field` | `ValueError` raised |
| **Bridge: No residue nested** | `test_experiment_spec_rejects_nested_speculative_content` | `ValueError` raised |
| **Bridge: Hints extraction** | `test_speculative_agent_extract_experiment_hints` | `ExperimentHints` produced |
| **Bridge: Steward catches hints** | `test_steward_rejects_experiment_hints_in_evidence_via_epistemic_status` | `ValueError` raised |
| **Bridge: VerifyAgent uses hints** | `test_verify_agent_design_uses_hints_for_template_selection` | `sensitivity_suite` selected |
| **Bridge: VerifyAgent fallback** | `test_verify_agent_design_falls_back_without_hints` | `numeric_consistency` default |

---

> **This contract is enforced by code, not by trust.**
>
> Any violation of these invariants will cause a hard failure at persistence time.
