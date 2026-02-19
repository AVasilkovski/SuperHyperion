# SuperHyperion Naming Strategy (Unified)

This document standardizes roadmap, branch, and commit naming for the Trust Runtime evolution.

## 1) Architecture/Roadmap Naming

- Use tracks: `EPI`, `OPS`, `TRUST`.
- Use milestone IDs: `<TRACK>-<MAJOR>.<MINOR>`.
  - Examples: `EPI-16.8`, `EPI-17.0`, `OPS-2.0`, `TRUST-1.1`.
- Do not use week-based labels in architecture docs.
- Use status enum only:
  - `PLANNED`
  - `ACTIVE`
  - `HARDENING`
  - `LOCKED`

## 2) Branch Naming

Format:

```text
<type>/<track>-<major>.<minor>-<short-scope>
```

Examples:

- `feat/epi-17.0-coverage-logging`
- `feat/trust-1.0-policy-core`
- `fix/ops-2.0-migration-runner`
- `docs/trust-runtime-series-roadmap`

## 3) Commit Naming (Conventional + Track Prefix)

Format:

```text
<type>(<track>): <summary>
```

Where `type` is one of:

- `feat`
- `fix`
- `refactor`
- `test`
- `docs`
- `chore`

Track values:

- `epi`
- `ops`
- `trust`
- `cross`

Examples:

- `feat(epi): add mutation-event linkage verification in replay`
- `fix(ops): fail closed when migration version missing`
- `docs(trust): define control-plane API surface`

## 4) PR Title Naming

Format:

```text
<TRACK>-<MAJOR>.<MINOR>: <capability summary>
```

Examples:

- `EPI-17.0: Introduce coverage logging and capsule summaries`
- `OPS-2.0: Add additive migration framework with schema version tracking`

## 5) Deprecation Rule

When legacy labels conflict with this strategy:

- Keep old labels only as historical references.
- All new work must use this naming strategy.
