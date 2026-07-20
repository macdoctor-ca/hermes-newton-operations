---
product: Newton Operations
surface: Hermes authenticated dashboard plugin
route: /operations
visual_posture: operational, explainable, calm
---

# Newton Operations design specification

## Product boundary

Newton Operations is an authenticated, profile-scoped operations cockpit. It observes bounded projections from native Hermes stores and links the operator back to native controls. It is not another gateway, scheduler, task authority, session store, memory system, or telemetry service. Only its append-only journal is writable.

## Information hierarchy

1. **System posture** — canonical gateway liveness, active agents, connected channels, snapshot time, and refresh controls.
2. **Primary metrics** — attention count, active work, recent cron reliability, and source-read health.
3. **Explainable attention** — severity, age, cause, recommended recovery, and native Hermes destination.
4. **Operations timeline** — a privacy-bounded chronological feed with source and text filters.
5. **Mission control** — Kanban dependencies/run posture and cron reliability history.
6. **Runtime context** — active delegations, processes, and recent sessions without payloads or identifiers.
7. **Source diagnostics** — availability, freshness, and schema compatibility for each independent read model.
8. **Decision journal** — decisions and outcomes with tags, related labels, supersession, sealing, integrity, filtering, and export.

## Visual rules

- Match Hermes's compact navigation and content density.
- Use the Hermes Teal vocabulary through host variables and components: monospace micro-labels, thin low-contrast borders, deep layered surfaces, restrained radii, and compact supporting text.
- Use no hardcoded color literals or external visual dependencies.
- Preserve substantial whitespace around the page hierarchy while keeping operational cards dense.
- Status indicators always include text; colour is never the only signal.
- Use short, explainable labels and omit native operational identifiers.
- Show generic recovery language rather than raw exceptions, commands, prompts, paths, or message content.
- Degraded sources remain independent; one unreadable source must not visually collapse the whole cockpit.

## Layout

- **Wide:** five metrics, full-width posture/attention/timeline, paired Kanban/Cron and runtime/session panels, then full-width diagnostics and journal.
- **Medium:** metrics collapse to three then two columns; all content panels stack when their bounded content benefits from width.
- **Narrow:** one column; control clusters wrap; timeline times move above content; forms and task facts become linear.
- **Print:** interactive controls disappear and panels avoid page breaks where practical.
- Visible lists are capped by the backend and remain independently scroll-free.

## Interaction

- Refresh every 10 seconds while work is active and every 30 seconds while idle.
- Pause polling while the document is hidden and refresh immediately when it becomes visible.
- Manual refresh remains available and disabled while a request is active.
- Timeline filters persist in the URL, not browser storage.
- Keyboard shortcuts require `Alt+Shift`: `R` refresh, `F` focus mode, `S` to enter Share Mode, and `/` for timeline search. Share Mode can be exited only through the confirmed on-screen control.
- Focus mode retains posture, attention, and timeline while hiding secondary panels.
- Native links navigate to Hermes's existing Kanban, Cron, and Sessions surfaces; Newton never performs those mutations. Native links are omitted in Share Mode.

## Share Mode

Share Mode replaces the complete live read model with server-generated neutral demonstration data before rendering, with the same neutral model available as an offline frontend fallback. The share endpoint does not read live Hermes or journal stores. It never merely obscures existing DOM text. Entering the mode clears user-entered filters and drafts, removes the journal form and native links, and requires a second explicit action before live data can be shown again. A visible `SANITIZED DEMO` watermark remains present in screen and print output. Share summaries are generated only from the active demonstration model.

## Journal

- Creation is explicit and disabled in Share Mode.
- Tags and related references are bounded labels, not arbitrary links.
- Supersession creates a new record pointing to an earlier record; history is never edited in place.
- Creation and sealing append events to a per-record SHA-256 chain. The UI shows bounded verification status rather than raw hashes.
- JSON and Markdown exports contain journal projections only.
- Additive metadata and event-chain migration occurs transactionally on the next journal write after an atomically published, verified, owner-only SQLite backup; read-only requests do not initialize or alter storage.

## Accessibility

- The plugin uses the host page landmark and does not nest another `main` element.
- Every panel has a semantic heading; controls and filters have text labels or accessible names.
- Status pills pair dots with text.
- Keyboard shortcuts ignore active inputs, text areas, and selects.
- Focus states resolve through host components and theme colours.
- Reduced-motion preferences disable Newton animations and transitions.
- Empty states distinguish healthy quiet from source failure.
