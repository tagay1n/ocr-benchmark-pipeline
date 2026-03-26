# AGENTS.md

## Purpose

Collaboration rules for engineers and coding agents working in this repository.

## Scope

Use only these living docs:

- `README.md`
- `AGENTS.md`

`PROJECT_CONTEXT.md` is intentionally removed.

## Working Rules

- Keep behavior docs in `README.md` accurate when APIs or UX flows change.
- Keep this file focused on process and engineering agreements.
- Do not commit secrets (especially API keys in `config.yaml`).
- Prefer small, test-backed changes.
- Use TDD by default for behavior changes: add or update a failing test first, implement the minimal fix, then run relevant tests.
- When touching backend logic, run backend tests.
- When touching frontend logic, run frontend tests.
- Keep API status values canonical in backend (frontend should not remap business semantics).

## Pipeline Invariants

- Pipeline progression is manual by default; no auto stage triggers from discovery or layout review.
- Manual actions (`Detect`, reextract, review submit) must remain available unless a local in-flight operation is active.
- Reviewer edits are draft-first and applied explicitly on review confirmation.

## UI/UX Invariants

- Destructive operations require explicit confirmation.
- Long-running actions should show immediate non-text busy feedback and lock duplicate submits.
- Activity/status should come from backend events, not transient ad-hoc frontend banners.
