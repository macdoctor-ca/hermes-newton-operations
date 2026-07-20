# Changelog

All notable changes to Newton Operations are documented here.

## [1.1.0] - 2026-07-19

### Added

- Unified, privacy-bounded operations timeline across gateway, sessions, delegations, processes, cron, Kanban, and journal records.
- Explainable attention cards with severity, age, rationale, recovery guidance, and links to native Hermes control surfaces.
- Kanban dependency aliases, bounded run history, heartbeat posture, retry state, and elapsed/runtime context without exposing native identifiers.
- Seven-run cron reliability strips, duration summaries, and overdue-schedule detection.
- Source diagnostics for read-model availability, freshness, and schema compatibility.
- Journal tags, related references, supersession links, per-record event-chain verification, bounded aggregate integrity status, filtering, and JSON/Markdown export.
- Privacy-safe Share Mode backed by a server-generated neutral snapshot that reads no live stores, plus print/export presentation and sanitized summary copying.
- Focus mode, URL-persisted timeline filters, keyboard shortcuts, adaptive polling, hidden-tab pausing, responsive layouts, and print styles.

### Changed

- Snapshot schema advanced to version 2 while retaining the existing authenticated endpoints and bounded component projections.
- Share Mode clears retained client inputs, omits native links and journal controls, and requires confirmation before returning to live data.
- Kanban projections use canonical task tenant and run profile ownership fields.
- Journal migration is additive, transactional, serialized, bounded, and backed by an atomically published verified owner-only SQLite backup; event schema is bound into tamper verification.
- GitHub Actions and the CI uv toolchain are pinned to reviewed immutable versions.

## [1.0.1] - 2026-07-19

- Rebuilt the public release history with neutral profile fixtures and GitHub noreply commit metadata.
- No runtime behavior changes from 1.0.0.

## [1.0.0] - 2026-07-19

### Added

- Native authenticated `/operations` dashboard for Hermes Agent.
- Profile-scoped summaries of gateway health, sessions, Kanban, cron, delegation, and background activity.
- Bounded append-only decision/outcome journal with deterministic sealing.
- Nonblocking, profile-isolated lifecycle markers.
- Canonical gateway PID/lock/process-identity liveness checks.
- Responsive Hermes Teal interface and complete privacy/security regression suite.
