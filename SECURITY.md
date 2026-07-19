# Newton Operations security model

## Trust boundary

This is trusted local code installed under the default Hermes profile and loaded by the authenticated Hermes dashboard. It does not open a listener, contact external services, or execute shell commands.

## Data minimization

The snapshot API may expose:

- Aggregate counts and states
- Hermes session titles, sources, timestamps, and usage counts
- Cron job names and state
- Kanban task titles, state, priority, and assignee
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
- Frontend polling is no faster than 15 seconds and stops on unmount.

## Profile isolation

- The dashboard resolves all native paths from the active `HERMES_HOME` and never enumerates sibling profile directories.
- Lifecycle hooks compare explicit Kanban profile metadata or the gateway session-key namespace with the installation profile.
- Ambiguous events and events from another profile are ignored before they reach the journal queue.

## Storage

- Journal database: `data/operations.db`, mode `0600`.
- Plugin/data directories: mode `0700`.
- Retention: 365 days.
- Maximum projected records: 2,000.
- No transcripts are copied.

## Security disclosures

Do not include production state, logs, prompts, identifiers, or credentials in a public issue. Use GitHub private vulnerability reporting for security-sensitive findings.

## Rollback

Disable the plugin and restart only the dashboard service. The gateway and messaging channels remain running unless hook code must be unloaded immediately. Journal data is preserved unless the operator explicitly deletes it.
