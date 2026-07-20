# Newton Operations security model

## Trust boundary

This is trusted local code installed under the default Hermes profile and loaded by the authenticated Hermes dashboard. It does not open a listener, contact external services, or execute shell commands.

## Data minimization

The snapshot API may expose:

- Aggregate counts and states
- Hermes session titles, sources, timestamps, and usage counts
- Cron job names and state
- Kanban task titles, state, priority, privacy-safe dependency aliases, run outcomes, and assignment presence
- Bounded process/delegation lifecycle summaries without identifiers
- Gateway platform names and connection state
- Explicitly entered decision-journal records

It must not expose:

- Conversation or prompt bodies
- Tool commands or command output
- Working directories or arbitrary paths
- System prompts or model configuration blobs
- Raw exception/error text
- Chat, thread, user, phone, or platform account identifiers
- Environment variables, tokens, passwords, hashes, cookies, or credentials
- Async delegation task/result JSON
- Cron prompts, scripts, work directories, or delivery targets

## Mutations

The only dashboard mutations are append/seal operations on the plugin-owned journal. Native Hermes stores are opened read-only or read as files; the plugin never edits sessions, cron, Kanban, processes, gateway state, memory, skills, or configuration.

## Availability

- Each native component is collected independently.
- Gateway health uses Hermes's runtime lock, PID record, process-identity, and kernel-start-time verifier; persisted `gateway_state.json` alone is never treated as proof of life.
- A missing, locked, malformed, or schema-drifted store marks only that component degraded.
- Response sizes and list lengths are bounded.
- SQLite reads use short timeouts and read-only URI mode.
- Lifecycle markers are queued on a bounded daemon worker; full queues drop observability markers instead of blocking Hermes.
- Frontend polling runs at 10 seconds only while work is active, backs off to 30 seconds while idle, pauses while hidden, and stops on unmount.

## Profile isolation

- The dashboard resolves all native paths from the active `HERMES_HOME` and never enumerates sibling profile directories.
- Kanban tasks are scoped by the canonical `tenant` field and task runs by `profile`; missing ownership columns fail closed.
- Lifecycle hooks compare explicit Kanban profile metadata or the gateway session-key namespace with the installation profile.
- Ambiguous events and events from another profile are ignored before they reach the journal queue.

## Share Mode

Share Mode requests `GET /snapshot?share=true`, whose server-generated neutral model is built without reading live Hermes or journal stores. React uses that model before creating dashboard elements, with a built-in neutral model as an offline fallback. It does not blur or cosmetically cover live values. Entering the mode clears retained filters and drafts; native links, the journal form, mutation controls, and exports are not rendered. Leaving the privacy boundary requires a second explicit confirmation and cannot be triggered by a bare-letter shortcut. The mode is visibly watermarked and copied summaries use only the active demonstration data.

## Storage

- Journal database: `data/operations.db`, mode `0600`.
- Plugin/data directories: mode `0700`.
- Retention: 365 days.
- Maximum projected records: 2,000.
- Metadata and event-chain columns migrate additively inside one transaction on the next write; read-only requests do not alter legacy databases. Migration is serialized across plugin processes, and a bounded, verified temporary backup is atomically promoted to the owner-only backup path before migration begins.
- Tags and related labels are bounded to six values; supersession points only to an existing journal record.
- Every retained event participates in an independent SHA-256 chain for its record. API projections expose only verification status, while `GET /journal/integrity` returns bounded aggregate status without raw hash material.
- JSON and Markdown export contains journal projections only.
- No transcripts are copied.

## Security disclosures

Do not include production state, logs, prompts, identifiers, or credentials in a public issue. Use GitHub private vulnerability reporting for security-sensitive findings.

## Rollback

Disable the plugin and restart only the dashboard service. The gateway and messaging channels remain running unless hook code must be unloaded immediately. Journal data is preserved unless the operator explicitly deletes it.
