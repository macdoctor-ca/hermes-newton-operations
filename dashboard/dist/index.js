(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  const registry = window.__HERMES_PLUGINS__;
  if (!SDK || !registry || typeof registry.register !== "function") return;

  const React = SDK.React;
  const h = React.createElement;
  const hooks = SDK.hooks;
  const C = SDK.components || {};
  const useState = hooks.useState;
  const useEffect = hooks.useEffect;
  const useCallback = hooks.useCallback;
  const useMemo = hooks.useMemo;
  const useRef = hooks.useRef;
  const ShareContext = React.createContext(false);

  const Card = C.Card || "section";
  const CardHeader = C.CardHeader || "header";
  const CardTitle = C.CardTitle || "h2";
  const CardContent = C.CardContent || "div";
  const Badge = C.Badge || "span";
  const Button = C.Button || "button";
  const Input = C.Input || "input";
  const Label = C.Label || "label";

  const API = "/api/plugins/newton-operations";
  const EMPTY = [];
  const DEMO = {
    schema_version: 2,
    generated_at: new Date().toISOString(),
    profile: "default",
    gateway: {
      status: "ok",
      state: "running",
      active_agents: 2,
      updated_at: new Date().toISOString(),
      platforms: [
        { name: "signal", state: "connected", updated_at: new Date().toISOString() },
        { name: "telegram", state: "connected", updated_at: new Date().toISOString() },
      ],
    },
    attention: {
      count: 1,
      items: [
        {
          title: "Release verification waiting",
          status: "blocked",
          severity: "warning",
          source: "kanban",
          why: "A dependent task is waiting for its verification prerequisite.",
          next_step: "Open Kanban and review the dependency chain.",
          age_seconds: 840,
          route: "/kanban",
        },
      ],
    },
    current_work: { count: 3, items: [] },
    timeline: {
      count: 5,
      items: [
        { source: "kanban", kind: "kanban", title: "Quality checks completed", status: "done", at: new Date().toISOString(), detail: "K02 · no open dependencies", route: "/kanban" },
        { source: "cron", kind: "cron", title: "Nightly backup verification", status: "success", at: new Date(Date.now() - 420000).toISOString(), detail: "Scheduled execution finished.", route: "/cron" },
        { source: "journal", kind: "decision", title: "Keep native stores authoritative", status: "sealed", at: new Date(Date.now() - 1200000).toISOString(), detail: "Newton observes Hermes and writes only to its bounded journal.", route: "/operations#journal" },
        { source: "sessions", kind: "session", title: "Operations review", status: "completed", at: new Date(Date.now() - 1800000).toISOString(), detail: "signal session metadata", route: "/sessions" },
        { source: "gateway", kind: "channel", title: "Signal channel", status: "connected", at: new Date(Date.now() - 2400000).toISOString(), detail: "", route: "/operations#gateway" },
      ],
    },
    kanban: {
      status: "ok",
      total: 8,
      active_count: 3,
      status_counts: { running: 1, ready: 1, blocked: 1, done: 5 },
      edges: [{ parent: "K01", child: "K03" }, { parent: "K02", child: "K03" }],
      items: [
        { node: "K01", title: "Implement operations timeline", status: "running", priority: 2, assignment: "assigned", heartbeat_state: "live", open_parent_count: 0, child_count: 1, attempt_count: 1, consecutive_failures: 0, elapsed_seconds: 620, max_runtime_seconds: 3600, run_history: [{ status: "running", outcome: "unknown", duration_seconds: 620 }], route: "/kanban" },
        { node: "K02", title: "Verify privacy boundaries", status: "ready", priority: 2, assignment: "assigned", heartbeat_state: "idle", open_parent_count: 0, child_count: 1, attempt_count: 0, consecutive_failures: 0, run_history: [], route: "/kanban" },
        { node: "K03", title: "Publish verified release", status: "blocked", priority: 1, assignment: "assigned", heartbeat_state: "idle", open_parent_count: 2, child_count: 0, attempt_count: 0, consecutive_failures: 0, run_history: [], route: "/kanban" },
      ],
    },
    cron: {
      status: "ok",
      total: 3,
      enabled_count: 3,
      overdue_count: 0,
      executions: [],
      jobs: [
        { name: "Nightly backup verification", enabled: true, state: "success", schedule: "daily at 02:00", no_agent: true, overdue: false, history: ["success", "success", "success", "success", "success", "success", "success"], reliability_percent: 100, last_duration_seconds: 42, route: "/cron" },
        { name: "Morning operations brief", enabled: true, state: "success", schedule: "daily at 08:00", no_agent: false, overdue: false, history: ["success", "success", "failed", "success", "success", "success", "success"], reliability_percent: 86, last_duration_seconds: 78, route: "/cron" },
      ],
    },
    sessions: {
      status: "ok",
      total: 4,
      items: [
        { title: "Operations review", source: "signal", model: "configured model", status: "active", updated_at: new Date().toISOString(), message_count: 12, tool_call_count: 8, route: "/sessions" },
        { title: "Release verification", source: "cli", model: "configured model", status: "completed", updated_at: new Date(Date.now() - 3600000).toISOString(), message_count: 6, tool_call_count: 11, route: "/sessions" },
      ],
    },
    delegations: { status: "ok", total: 2, active_count: 1, items: [{ title: "Delegated agent task", state: "running", delivery_state: "pending", elapsed_seconds: 380, updated_at: new Date().toISOString(), route: "/operations#runtime" }] },
    processes: { status: "ok", count: 1, items: [{ title: "Background process", status: "running", elapsed_seconds: 245, notify_on_complete: true, route: "/operations#runtime" }] },
    diagnostics: {
      status: "ok",
      count: 7,
      items: ["gateway", "sessions", "delegations", "processes", "cron", "kanban", "journal"].map(function (source) {
        return { source: source, status: "ok", freshness: "fresh", schema: "compatible", detail: "Source read succeeded with a compatible bounded projection.", latest_at: new Date().toISOString(), route: "/operations#diagnostics" };
      }),
    },
    journal: {
      status: "ok",
      count: 2,
      items: [
        { record_id: "demo0000000000000000000000000001", category: "decision", title: "Keep native stores authoritative", summary: "Newton observes Hermes and writes only to its bounded journal.", source: "manual", tags: ["architecture", "privacy"], related: ["Operations dashboard"], status: "sealed", created_at: new Date(Date.now() - 7200000).toISOString(), updated_at: new Date(Date.now() - 7100000).toISOString(), sealed_at: new Date(Date.now() - 7100000).toISOString(), integrity_status: "verified", event_count: 2 },
        { record_id: "demo0000000000000000000000000002", category: "outcome", title: "Release checks completed", summary: "Quality, security, privacy, and clean-install verification passed.", source: "manual", tags: ["release"], related: ["Kanban release task"], status: "open", created_at: new Date(Date.now() - 3600000).toISOString(), updated_at: new Date(Date.now() - 3600000).toISOString(), integrity_status: "verified", event_count: 1 },
      ],
    },
  };

  function api(path, options) {
    return SDK.fetchJSON(API + path, options);
  }

  function isObject(value) {
    return !!value && typeof value === "object" && !Array.isArray(value);
  }

  function array(value, key) {
    if (Array.isArray(value)) return value;
    if (isObject(value) && Array.isArray(value[key || "items"])) return value[key || "items"];
    return EMPTY;
  }

  function text(value, fallback) {
    if (value === undefined || value === null || value === "") return fallback || "—";
    return String(value);
  }

  function number(value, fallback) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback || 0;
  }

  function stateOf(item, fallback) {
    if (!isObject(item)) return text(item, fallback || "unknown");
    return text(item.status || item.state || item.outcome, fallback || "unknown");
  }

  function toneOf(value) {
    const normalized = String(value || "").toLowerCase();
    if (/healthy|online|ready|running|active|enabled|complete|completed|connected|success|ok|sealed|fresh|compatible|live/.test(normalized)) return "good";
    if (/blocked|failed|error|critical|offline|dead|unavailable|overdue|timeout|stopped/.test(normalized)) return "critical";
    if (/warning|attention|stale|paused|waiting|degraded|pending|retrying|reconnecting|unknown/.test(normalized)) return "warning";
    return "neutral";
  }

  function formatTime(value) {
    if (value === undefined || value === null || value === "") return "Not reported";
    const date = new Date(typeof value === "number" && value < 100000000000 ? value * 1000 : value);
    if (Number.isNaN(date.getTime())) return text(value, "Not reported");
    return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  }

  function relativeTime(value) {
    if (value === undefined || value === null || value === "") return "Not reported";
    try {
      const date = new Date(typeof value === "number" && value < 100000000000 ? value * 1000 : value);
      if (Number.isNaN(date.getTime())) return formatTime(value);
      const delta = Math.max(0, Date.now() - date.getTime());
      const seconds = Math.floor(delta / 1000);
      if (seconds < 60) return "just now";
      if (seconds < 3600) return Math.floor(seconds / 60) + "m ago";
      if (seconds < 86400) return Math.floor(seconds / 3600) + "h ago";
      return Math.floor(seconds / 86400) + "d ago";
    } catch (_) {
      return formatTime(value);
    }
  }

  function duration(value) {
    const seconds = number(value, 0);
    if (!seconds) return "—";
    if (seconds < 60) return seconds + "s";
    if (seconds < 3600) return Math.floor(seconds / 60) + "m " + (seconds % 60) + "s";
    return Math.floor(seconds / 3600) + "h " + Math.floor((seconds % 3600) / 60) + "m";
  }

  function join(values) {
    return values.filter(function (value) { return value !== undefined && value !== null && value !== "" && value !== "—"; }).join(" · ");
  }

  function keyFor(item, index, prefix) {
    const base = item && (item.record_id || item.node || item.name || item.title);
    return prefix + "-" + text(base, "item") + "-" + String(index);
  }

  function StatusPill(props) {
    const value = text(props.value, "unknown");
    return h(Badge, { className: "newton-status newton-status--" + (props.tone || toneOf(value)) },
      h("span", { className: "newton-status__dot", "aria-hidden": "true" }), props.label || value);
  }

  function Metric(props) {
    return h("div", { className: "newton-metric newton-metric--" + (props.tone || "neutral") },
      h("span", { className: "newton-metric__label" }, props.label),
      h("strong", { className: "newton-metric__value" }, text(props.value, "0")),
      props.hint ? h("span", { className: "newton-metric__hint" }, props.hint) : null);
  }

  function NativeLink(props) {
    const shareMode = React.useContext(ShareContext);
    if (!props.href || shareMode) return null;
    return h("a", { className: props.className || "newton-native-link", href: props.href }, props.children || "Open native view", h("span", { "aria-hidden": "true" }, " ↗"));
  }

  function Panel(props) {
    return h(Card, { id: props.id, className: "newton-panel " + (props.className || "") },
      h(CardHeader, { className: "newton-panel__header" },
        h("div", { className: "newton-section-heading" },
          h("div", { className: "newton-section-heading__index", "aria-hidden": "true" }, props.index),
          h("div", { className: "newton-section-heading__copy" },
            props.eyebrow ? h("span", { className: "newton-eyebrow" }, props.eyebrow) : null,
            h(CardTitle, { className: "newton-section-heading__title" }, props.title)),
          props.meta ? h("div", { className: "newton-section-heading__meta" }, props.meta) : null)),
      h(CardContent, { className: "newton-panel__content" }, props.children));
  }

  function EmptyState(props) {
    return h("div", { className: "newton-empty" },
      h("span", { className: "newton-empty__mark", "aria-hidden": "true" }, "✓"),
      h("div", null, h("strong", null, props.title || "Nothing needs attention"), props.children ? h("p", null, props.children) : null));
  }

  function GatewayPanel(props) {
    const gateway = props.gateway || {};
    const platforms = array(gateway, "platforms");
    const state = stateOf(gateway, "unknown");
    return h(Panel, { id: "gateway", index: "01", eyebrow: "System posture", title: "Gateway health", meta: text(gateway.status, "unknown"), className: "newton-panel--gateway" },
      h("div", { className: "newton-gateway" },
        h("div", { className: "newton-gateway__signal newton-gateway__signal--" + toneOf(state) },
          h("span", { className: "newton-gateway__pulse", "aria-hidden": "true" }),
          h("div", null, h("strong", null, state), h("span", null, "Canonical process verification"))),
        h("dl", { className: "newton-facts" },
          h("dt", null, "Profile"), h("dd", null, text(gateway.profile || props.profile, "default")),
          h("dt", null, "Active agents"), h("dd", null, number(gateway.active_agents, 0)),
          h("dt", null, "Channels"), h("dd", null, platforms.length),
          h("dt", null, "Updated"), h("dd", null, relativeTime(gateway.updated_at)))) ,
      platforms.length ? h("div", { className: "newton-channel-strip", "aria-label": "Gateway channels" },
        platforms.map(function (platform, index) {
          return h("div", { className: "newton-channel", key: keyFor(platform, index, "channel") },
            h("span", null, text(platform.name, "channel")), h(StatusPill, { value: stateOf(platform) }));
        })) : null);
  }

  function AttentionPanel(props) {
    const items = props.items;
    return h(Panel, { id: "attention", index: "02", eyebrow: "Explainable triage", title: "Needs attention", meta: items.length + " signals", className: "newton-panel--attention" },
      items.length ? h("ul", { className: "newton-attention-grid" }, items.map(function (item, index) {
        return h("li", { className: "newton-attention-card newton-attention-card--" + text(item.severity, "warning"), key: keyFor(item, index, "attention") },
          h("div", { className: "newton-attention-card__head" },
            h("span", { className: "newton-source-mark" }, text(item.source, "system")),
            h(StatusPill, { value: item.status, tone: item.severity === "critical" ? "critical" : "warning" })),
          h("strong", { className: "newton-attention-card__title" }, text(item.title, "Operational notice")),
          h("p", null, text(item.why, "This item requires review.")),
          h("div", { className: "newton-attention-card__step" }, h("span", null, "Next"), text(item.next_step, "Open the native Hermes page.")),
          h("div", { className: "newton-attention-card__footer" },
            h("span", null, item.age_seconds === null || item.age_seconds === undefined ? "Age unknown" : duration(item.age_seconds) + " old"),
            h(NativeLink, { href: item.route }, "Review")));
      })) : h(EmptyState, { title: "Operationally clear" }, "No bounded source is currently asking for intervention."));
  }

  function TimelinePanel(props) {
    const sources = ["all"].concat(Array.from(new Set(props.allItems.map(function (item) { return item.source; }))));
    const shown = props.expanded ? props.items : props.items.slice(0, 12);
    return h(Panel, { id: "timeline", index: "03", eyebrow: "Unified event stream", title: "Operations timeline", meta: shown.length + " of " + props.items.length, className: "newton-panel--timeline" },
      h("div", { className: "newton-toolbar" },
        h("div", { className: "newton-filter-pills", role: "group", "aria-label": "Timeline source filter" }, sources.map(function (source) {
          return h("button", { type: "button", key: source, className: "newton-filter-pill " + (props.source === source ? "is-active" : ""), "aria-pressed": props.source === source, onClick: function () { props.onSource(source); } }, source);
        })),
        h(Input, { ref: props.searchRef, className: "newton-search", type: "search", value: props.query, disabled: props.readOnly, placeholder: props.readOnly ? "Search disabled in Share Mode" : "Filter timeline…", "aria-label": "Filter operations timeline", onChange: function (event) { props.onQuery(event.target.value); } })),
      shown.length ? h("ol", { className: "newton-timeline" }, shown.map(function (item, index) {
        return h("li", { className: "newton-timeline__item", key: keyFor(item, index, "event") },
          h("span", { className: "newton-timeline__rail newton-timeline__rail--" + toneOf(item.status), "aria-hidden": "true" }),
          h("div", { className: "newton-timeline__time" }, h("strong", null, relativeTime(item.at)), h("span", null, formatTime(item.at))),
          h("div", { className: "newton-timeline__body" },
            h("div", { className: "newton-timeline__headline" }, h("span", { className: "newton-source-mark" }, text(item.source, "system")), h("strong", null, text(item.title, "Operational event")), h(StatusPill, { value: item.status })),
            item.detail ? h("p", null, item.detail) : null),
          h(NativeLink, { href: item.route }, "Open"));
      })) : h(EmptyState, { title: "No matching events" }, "Adjust the source or text filter."),
      props.items.length > 12 ? h("button", { type: "button", className: "newton-expand", "aria-expanded": props.expanded, onClick: props.onToggle }, props.expanded ? "Show latest 12" : "Show all " + props.items.length + " events") : null);
  }

  function KanbanPanel(props) {
    const section = props.section || {};
    const items = array(section, "items");
    const edges = array(section, "edges");
    return h(Panel, { id: "kanban", index: "04", eyebrow: "Mission control", title: "Kanban flow", meta: items.length + " active", className: "newton-panel--kanban" },
      edges.length ? h("div", { className: "newton-dependency-strip", "aria-label": "Visible Kanban dependencies" }, edges.map(function (edge, index) {
        return h("span", { key: "edge-" + index }, edge.parent, h("b", { "aria-hidden": "true" }, "→"), edge.child);
      })) : h("div", { className: "newton-inline-note" }, "No visible dependency edges in the bounded task set."),
      items.length ? h("div", { className: "newton-task-grid" }, items.map(function (item, index) {
        const attempts = array(item, "run_history");
        return h("article", { className: "newton-task", key: keyFor(item, index, "task") },
          h("div", { className: "newton-task__head" }, h("span", { className: "newton-node" }, text(item.node, "K")), h(StatusPill, { value: item.status })),
          h("strong", { className: "newton-task__title" }, text(item.title, "Kanban task")),
          h("div", { className: "newton-task__stats" },
            h("span", null, h("b", null, number(item.open_parent_count, 0)), " open parents"),
            h("span", null, h("b", null, number(item.attempt_count, attempts.length)), " attempts"),
            h("span", null, h("b", null, text(item.heartbeat_state, "unknown")), " heartbeat")),
          item.max_runtime_seconds ? h("div", { className: "newton-runtime-meter", title: "Elapsed versus maximum runtime" },
            h("span", { style: { width: Math.min(100, Math.round(number(item.elapsed_seconds, 0) / number(item.max_runtime_seconds, 1) * 100)) + "%" } })) : null,
          attempts.length ? h("div", { className: "newton-run-strip", "aria-label": "Recent run outcomes" }, attempts.slice().reverse().map(function (run, runIndex) {
            return h("span", { key: "run-" + runIndex, className: "newton-run-dot newton-run-dot--" + toneOf(run.outcome || run.status), title: text(run.outcome || run.status, "unknown") });
          })) : null,
          h(NativeLink, { href: item.route }, "Open Kanban"));
      })) : h(EmptyState, { title: "No active Kanban work" }, "Hermes remains the task authority."));
  }

  function CronPanel(props) {
    const section = props.section || {};
    const jobs = array(section, "jobs");
    const shown = props.expanded ? jobs : jobs.slice(0, 6);
    return h(Panel, { id: "cron", index: "05", eyebrow: "Reliability", title: "Cron schedule", meta: number(section.enabled_count, 0) + " enabled", className: "newton-panel--cron" },
      shown.length ? h("div", { className: "newton-cron-list" }, shown.map(function (job, index) {
        const history = Array.isArray(job.history) ? job.history : EMPTY;
        return h("article", { className: "newton-cron-job", key: keyFor(job, index, "cron") },
          h("div", { className: "newton-cron-job__head" }, h("strong", null, text(job.name, "Scheduled job")), h(StatusPill, { value: job.overdue ? "overdue" : job.state })),
          h("p", null, join([text(job.schedule, "Schedule unavailable"), job.no_agent ? "script-only" : "agent-driven", duration(job.last_duration_seconds)])),
          h("div", { className: "newton-cron-history", "aria-label": "Recent execution outcomes" },
            history.length ? history.map(function (result, resultIndex) { return h("span", { key: "result-" + resultIndex, className: "newton-cron-cell newton-cron-cell--" + toneOf(result), title: result }, toneOf(result) === "good" ? "✓" : toneOf(result) === "critical" ? "×" : "·"); }) : h("span", { className: "newton-cron-empty" }, "No execution history"),
            job.reliability_percent !== null && job.reliability_percent !== undefined ? h("strong", null, job.reliability_percent + "%") : null),
          h(NativeLink, { href: job.route }, "Open Cron"));
      })) : h(EmptyState, { title: "No scheduled jobs" }, "Cron remains managed by Hermes."),
      jobs.length > 6 ? h("button", { type: "button", className: "newton-expand", "aria-expanded": props.expanded, onClick: props.onToggle }, props.expanded ? "Show first 6" : "Show all " + jobs.length + " jobs") : null);
  }

  function RuntimePanel(props) {
    const delegations = array(props.delegations || {}, "items");
    const processes = array(props.processes || {}, "items");
    const rows = delegations.map(function (item) { return Object.assign({ surface: "delegation" }, item); }).concat(processes.map(function (item) { return Object.assign({ surface: "process" }, item); }));
    return h(Panel, { id: "runtime", index: "06", eyebrow: "Active execution", title: "Agents & processes", meta: rows.length + " active", className: "newton-panel--runtime" },
      rows.length ? h("ul", { className: "newton-compact-list" }, rows.map(function (item, index) {
        return h("li", { key: keyFor(item, index, "runtime") },
          h("span", { className: "newton-source-mark" }, item.surface),
          h("div", null, h("strong", null, text(item.title, item.surface)), h("span", null, join([duration(item.elapsed_seconds), item.notify_on_complete ? "completion notice" : "bounded metadata"]))),
          h(StatusPill, { value: stateOf(item) }));
      })) : h(EmptyState, { title: "Runtime is quiet" }, "No bounded delegations or background processes are active."));
  }

  function SessionsPanel(props) {
    const items = array(props.section || {}, "items");
    return h(Panel, { id: "sessions", index: "07", eyebrow: "Recent context", title: "Recent sessions", meta: items.length + " shown", className: "newton-panel--sessions" },
      items.length ? h("ul", { className: "newton-compact-list" }, items.map(function (item, index) {
        return h("li", { key: keyFor(item, index, "session") },
          h("span", { className: "newton-source-mark" }, text(item.source, "session")),
          h("div", null, h("strong", null, text(item.title, "Untitled session")), h("span", null, join([relativeTime(item.updated_at), number(item.message_count, 0) + " messages", number(item.tool_call_count, 0) + " tools"]))),
          h(StatusPill, { value: item.status }));
      })) : h(EmptyState, { title: "No recent sessions" }, "The profile session store has no bounded records to display."));
  }

  function DiagnosticsPanel(props) {
    const items = array(props.section || {}, "items");
    return h(Panel, { id: "diagnostics", index: "08", eyebrow: "Read-model integrity", title: "Data sources", meta: items.length + " checked", className: "newton-panel--diagnostics" },
      h("div", { className: "newton-diagnostics-grid" }, items.map(function (item, index) {
        return h("article", { className: "newton-diagnostic", key: keyFor(item, index, "source") },
          h("div", { className: "newton-diagnostic__head" }, h("strong", null, text(item.source, "source")), h(StatusPill, { value: item.freshness })),
          h("p", null, text(item.detail, "Bounded source state unavailable.")),
          h("div", { className: "newton-diagnostic__meta" }, h("span", null, text(item.schema, "unverified")), h("span", null, relativeTime(item.latest_at)), h(NativeLink, { href: item.route }, "Open")));
      })));
  }

  function JournalRecord(props) {
    const record = props.record;
    return h("li", { className: "newton-record" },
      h("span", { className: "newton-record__marker", "aria-hidden": "true" }, String(props.index + 1).padStart(2, "0")),
      h("div", { className: "newton-record__body" },
        h("div", { className: "newton-record__head" }, h("span", { className: "newton-record__kind" }, text(record.category, "record")), h(StatusPill, { value: record.status })),
        h("strong", { className: "newton-record__title" }, text(record.title, "Journal record")),
        h("p", { className: "newton-record__summary" }, text(record.summary, "No summary")),
        Array.isArray(record.tags) && record.tags.length ? h("div", { className: "newton-tag-row" }, record.tags.map(function (tag) { return h("span", { key: tag }, "#" + tag); })) : null,
        Array.isArray(record.related) && record.related.length ? h("p", { className: "newton-record__related" }, "Related: " + record.related.join(", ")) : null,
        record.supersedes ? h("p", { className: "newton-record__relation" }, "Supersedes an earlier journal record") : null,
        record.superseded_by ? h("p", { className: "newton-record__relation" }, "Superseded by a newer journal record") : null,
        h("span", { className: "newton-record__time" }, join([relativeTime(record.updated_at || record.created_at), "integrity " + text(record.integrity_status, "unverified")]))),
      record.status !== "sealed" && !props.readOnly ? h(Button, { className: "newton-seal-action", type: "button", disabled: props.busy, onClick: function () { props.onSeal(record.record_id); } }, props.busy ? "Sealing…" : "Seal") : record.status === "sealed" ? h("span", { className: "newton-sealed-mark", title: "Per-record event hash chain verified" }, "✓") : h("span", { className: "newton-sealed-mark", title: "Mutation controls are unavailable in Share Mode" }, "Demo"));
  }

  function JournalPanel(props) {
    const records = props.records;
    const supersedableRecords = props.allRecords.filter(function (record) { return record.category !== "lifecycle"; });
    return h(Panel, { id: "journal", index: "09", eyebrow: "Append-only operator memory", title: "Decision & outcome journal", meta: records.length + " visible", className: "newton-panel--journal" },
      h("div", { className: "newton-journal-actions" },
        h(Input, { type: "search", value: props.query, disabled: props.shareMode, placeholder: props.shareMode ? "Search disabled in Share Mode" : "Search journal…", "aria-label": "Search decision and outcome journal", onChange: function (event) { props.onQuery(event.target.value); } }),
        h("select", { className: "newton-select", value: props.statusFilter, disabled: props.shareMode, "aria-label": "Filter journal status", onChange: function (event) { props.onStatusFilter(event.target.value); } },
          h("option", { value: "all" }, "All records"), h("option", { value: "open" }, "Open"), h("option", { value: "sealed" }, "Sealed")),
        props.shareMode ? null : h("a", { className: "newton-export-link", href: API + "/journal/export?format=markdown", download: "newton-operations-journal.md" }, "Export Markdown"),
        props.shareMode ? null : h("a", { className: "newton-export-link", href: API + "/journal/export?format=json", download: "newton-operations-journal.json" }, "Export JSON")),
      h("div", { className: "newton-journal-layout" },
        props.shareMode ? h("div", { className: "newton-share-journal-note", role: "note" }, h("strong", null, "Journal mutations are unavailable in Share Mode"), h("p", null, "This panel contains neutral demonstration records only. Exit Share Mode to create or seal a real record.")) : h("form", { className: "newton-journal-form", onSubmit: props.onSubmit },
          h("div", { className: "newton-form-heading" }, h("strong", null, "Record what changed"), h("p", null, "Use concise, privacy-safe language. Corrections become linked records rather than edits.")),
          h("div", { className: "newton-form-grid" },
            h("div", { className: "newton-field" }, h(Label, { htmlFor: "newton-kind" }, "Type"), h("select", { id: "newton-kind", className: "newton-select", value: props.form.category, onChange: function (event) { props.onForm("category", event.target.value); } }, h("option", { value: "decision" }, "Decision"), h("option", { value: "outcome" }, "Outcome"))),
            h("div", { className: "newton-field" }, h(Label, { htmlFor: "newton-title" }, "Title"), h(Input, { id: "newton-title", value: props.form.title, maxLength: 120, required: true, onChange: function (event) { props.onForm("title", event.target.value); } })),
            h("div", { className: "newton-field newton-field--wide" }, h(Label, { htmlFor: "newton-summary" }, "Summary"), h("textarea", { id: "newton-summary", className: "newton-textarea", value: props.form.summary, maxLength: 500, required: true, onChange: function (event) { props.onForm("summary", event.target.value); } })),
            h("div", { className: "newton-field" }, h(Label, { htmlFor: "newton-tags" }, "Tags"), h(Input, { id: "newton-tags", value: props.form.tags, placeholder: "release, privacy", onChange: function (event) { props.onForm("tags", event.target.value); } })),
            h("div", { className: "newton-field" }, h(Label, { htmlFor: "newton-related" }, "Related references"), h(Input, { id: "newton-related", value: props.form.related, placeholder: "Kanban release task", onChange: function (event) { props.onForm("related", event.target.value); } })),
            h("div", { className: "newton-field newton-field--wide" }, h(Label, { htmlFor: "newton-supersedes" }, "Supersedes"), h("select", { id: "newton-supersedes", className: "newton-select", value: props.form.supersedes, onChange: function (event) { props.onForm("supersedes", event.target.value); } }, h("option", { value: "" }, "No earlier record"), supersedableRecords.map(function (record) { return h("option", { key: record.record_id, value: record.record_id }, text(record.title, "Journal record")); })))),
          h("div", { className: "newton-form-actions" }, h("span", { className: "newton-form-limit" }, props.form.summary.length + " / 500"), h(Button, { className: "newton-primary-action", type: "submit", disabled: props.busy || !props.form.title.trim() || !props.form.summary.trim() }, props.busy ? "Adding…" : "Add to journal")),
          props.notice ? h("div", { className: "newton-notice newton-notice--" + props.notice.tone, role: "status" }, props.notice.message) : null),
        h("div", { className: "newton-journal-records" }, records.length ? h("ol", { className: "newton-records" }, records.map(function (record, index) { return h(JournalRecord, { key: record.record_id || index, record: record, index: index, readOnly: props.shareMode, busy: props.busyRecord === record.record_id, onSeal: props.onSeal }); })) : h(EmptyState, { title: "No matching journal records" }, "Create a decision or adjust the search filter."))));
  }

  function NewtonOperationsPage() {
    const params = new URLSearchParams(window.location.search);
    const [snapshot, setSnapshot] = useState(null);
    const [shareSnapshot, setShareSnapshot] = useState(null);
    const [health, setHealth] = useState(null);
    const [journal, setJournal] = useState({ status: "ok", count: 0, items: [] });
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [loadError, setLoadError] = useState("");
    const [shareMode, setShareMode] = useState(params.get("share") === "1");
    const [focusMode, setFocusMode] = useState(params.get("focus") === "1");
    const [timelineSource, setTimelineSource] = useState(params.get("source") || "all");
    const [timelineQuery, setTimelineQuery] = useState(params.get("q") || "");
    const [timelineExpanded, setTimelineExpanded] = useState(false);
    const [cronExpanded, setCronExpanded] = useState(false);
    const [journalQuery, setJournalQuery] = useState("");
    const [journalStatus, setJournalStatus] = useState("all");
    const [journalBusy, setJournalBusy] = useState(false);
    const [busyRecord, setBusyRecord] = useState("");
    const [notice, setNotice] = useState(null);
    const [exitShareArmed, setExitShareArmed] = useState(false);
    const [form, setForm] = useState({ category: "decision", title: "", summary: "", tags: "", related: "", supersedes: "" });
    const searchRef = useRef(null);
    const requestGeneration = useRef(0);
    const mounted = useRef(true);

    useEffect(function () {
      mounted.current = true;
      return function () { mounted.current = false; requestGeneration.current += 1; };
    }, []);

    const loadData = useCallback(async function (manual) {
      const generation = requestGeneration.current + 1;
      requestGeneration.current = generation;
      if (manual) setRefreshing(true);
      try {
        if (shareMode) {
          const shared = await api("/snapshot?share=true");
          if (!mounted.current || requestGeneration.current !== generation) return;
          setShareSnapshot(shared);
          setHealth({ status: "healthy" });
          setJournal(shared.journal || { status: "ok", count: 0, items: [] });
        } else {
          const values = await Promise.all([api("/snapshot"), api("/health"), api("/journal?limit=100")]);
          if (!mounted.current || requestGeneration.current !== generation) return;
          setSnapshot(values[0]);
          setHealth(values[1]);
          setJournal(values[2]);
        }
        setLoadError("");
      } catch (_) {
        if (mounted.current && requestGeneration.current === generation) setLoadError("Newton could not refresh one or more bounded read models.");
      } finally {
        if (mounted.current && requestGeneration.current === generation) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    }, [shareMode]);

    useEffect(function () { loadData(false); }, [loadData]);

    const activeCount = snapshot ? number(snapshot.current_work && snapshot.current_work.count, 0) : 0;
    useEffect(function () {
      let timer = null;
      let cancelled = false;
      function clearTimer() {
        if (timer) window.clearTimeout(timer);
        timer = null;
      }
      function schedule() {
        clearTimer();
        if (cancelled || document.hidden) return;
        const delay = activeCount > 0 ? 10000 : 30000;
        timer = window.setTimeout(async function () {
          timer = null;
          if (cancelled || document.hidden) return;
          await loadData(false);
          schedule();
        }, delay);
      }
      async function visibilityChanged() {
        if (document.hidden) {
          clearTimer();
          return;
        }
        await loadData(false);
        schedule();
      }
      schedule();
      document.addEventListener("visibilitychange", visibilityChanged);
      return function () { cancelled = true; clearTimer(); document.removeEventListener("visibilitychange", visibilityChanged); };
    }, [loadData, activeCount]);

    useEffect(function () {
      const next = new URLSearchParams();
      if (focusMode) next.set("focus", "1");
      if (shareMode) next.set("share", "1");
      if (timelineSource !== "all") next.set("source", timelineSource);
      if (timelineQuery) next.set("q", timelineQuery);
      const query = next.toString();
      window.history.replaceState(null, "", window.location.pathname + (query ? "?" + query : "") + window.location.hash);
    }, [focusMode, shareMode, timelineSource, timelineQuery]);

    useEffect(function () {
      if (!shareMode) return;
      setTimelineSource("all");
      setTimelineQuery("");
      setJournalQuery("");
      setJournalStatus("all");
      setForm({ category: "decision", title: "", summary: "", tags: "", related: "", supersedes: "" });
      setNotice(null);
    }, [shareMode]);

    useEffect(function () {
      if (!exitShareArmed) return;
      const timer = window.setTimeout(function () { setExitShareArmed(false); }, 5000);
      return function () { window.clearTimeout(timer); };
    }, [exitShareArmed]);

    useEffect(function () {
      function keyboard(event) {
        const tag = document.activeElement && document.activeElement.tagName;
        const typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
        if (typing || event.metaKey || event.ctrlKey || !event.altKey || !event.shiftKey) return;
        const key = event.key.toLowerCase();
        if (key === "/" && !shareMode) { event.preventDefault(); if (searchRef.current) searchRef.current.focus(); }
        if (key === "r" && !shareMode) { event.preventDefault(); loadData(true); }
        if (key === "f") { event.preventDefault(); setFocusMode(function (value) { return !value; }); }
        if (key === "s" && !shareMode) { event.preventDefault(); setShareMode(true); }
      }
      window.addEventListener("keydown", keyboard);
      return function () { window.removeEventListener("keydown", keyboard); };
    }, [loadData, shareMode]);

    const view = shareMode ? (shareSnapshot || DEMO) : (snapshot || {});
    const viewHealth = shareMode ? { status: "healthy" } : (health || {});
    const allTimeline = array(view.timeline || {}, "items");
    const filteredTimeline = useMemo(function () {
      const query = timelineQuery.trim().toLowerCase();
      return allTimeline.filter(function (item) {
        if (timelineSource !== "all" && item.source !== timelineSource) return false;
        if (!query) return true;
        return [item.title, item.detail, item.source, item.status, item.kind].join(" ").toLowerCase().indexOf(query) !== -1;
      });
    }, [allTimeline, timelineSource, timelineQuery]);

    const realRecords = array(journal, "items");
    const allRecords = shareMode ? array(view.journal || {}, "items") : realRecords;
    const filteredRecords = useMemo(function () {
      const query = journalQuery.trim().toLowerCase();
      return allRecords.filter(function (record) {
        if (journalStatus !== "all" && record.status !== journalStatus) return false;
        if (!query) return true;
        return [record.title, record.summary].concat(record.tags || [], record.related || []).join(" ").toLowerCase().indexOf(query) !== -1;
      });
    }, [allRecords, journalQuery, journalStatus]);

    function updateForm(field, value) { setForm(function (current) { return Object.assign({}, current, { [field]: value }); }); }
    function parseList(value, lower) {
      return value.split(",").map(function (item) { return lower ? item.trim().toLowerCase() : item.trim(); }).filter(Boolean).slice(0, 6);
    }
    async function submitJournal(event) {
      event.preventDefault();
      if (shareMode) { setNotice({ tone: "warning", message: "Share mode is a sanitized preview; journal writes are disabled." }); return; }
      setJournalBusy(true); setNotice(null);
      try {
        await api("/journal", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ category: form.category, title: form.title.trim(), summary: form.summary.trim(), tags: parseList(form.tags, true), related: parseList(form.related, false), supersedes: form.supersedes || null }) });
        setForm({ category: "decision", title: "", summary: "", tags: "", related: "", supersedes: "" });
        setNotice({ tone: "good", message: "Journal record added. Seal it when the decision or outcome is final." });
        await loadData(false);
      } catch (_) { setNotice({ tone: "critical", message: "The journal rejected this record. Check lengths, tags, and linked record." }); }
      finally { setJournalBusy(false); }
    }
    async function sealRecord(recordId) {
      if (shareMode) return;
      setBusyRecord(recordId); setNotice(null);
      try { await api("/journal/" + encodeURIComponent(recordId) + "/seal", { method: "POST" }); setNotice({ tone: "good", message: "Record sealed and its event hash chain verified." }); await loadData(false); }
      catch (_) { setNotice({ tone: "critical", message: "The record could not be sealed." }); }
      finally { setBusyRecord(""); }
    }
    function toggleShareMode() {
      if (!shareMode) {
        setExitShareArmed(false);
        setShareMode(true);
        return;
      }
      if (!exitShareArmed) {
        setExitShareArmed(true);
        setNotice({ tone: "warning", message: "Select Confirm live view within five seconds to leave the privacy boundary." });
        return;
      }
      setExitShareArmed(false);
      setNotice(null);
      setShareMode(false);
    }
    function copyShareSummary() {
      const summaryJobs = array(view.cron || {}, "jobs");
      const summaryReliability = summaryJobs.map(function (job) { return job.reliability_percent; }).filter(function (value) { return value !== null && value !== undefined; });
      const reliability = summaryReliability.length ? Math.round(summaryReliability.reduce(function (sum, value) { return sum + number(value, 0); }, 0) / summaryReliability.length) + "%" : "not reported";
      const summary = ["Newton Operations — SANITIZED DEMO", "Gateway: " + stateOf(view.gateway || {}), "Attention: " + array(view.attention || {}, "items").length, "Active work: " + number(view.current_work && view.current_work.count, 0), "Cron reliability: " + reliability, "No live operational data is included."].join("\n");
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(summary).then(function () { setNotice({ tone: "good", message: "Sanitized operations summary copied." }); }).catch(function () { setNotice({ tone: "warning", message: "Clipboard access was not available." }); });
    }

    if (loading && !snapshot) return h("div", { className: "newton-ops newton-loading", role: "status" }, h("span", { className: "newton-loading__pulse", "aria-hidden": "true" }), h("div", null, h("strong", null, "Reading bounded operations state"), h("p", null, "Hermes remains fully authoritative.")));

    const attention = array(view.attention || {}, "items");
    const cronJobs = array(view.cron || {}, "jobs");
    const reliabilityValues = cronJobs.map(function (job) { return job.reliability_percent; }).filter(function (value) { return value !== null && value !== undefined; });
    const averageReliability = reliabilityValues.length ? Math.round(reliabilityValues.reduce(function (sum, value) { return sum + number(value, 0); }, 0) / reliabilityValues.length) + "%" : "—";
    const diagnostics = array(view.diagnostics || {}, "items");
    const healthySources = diagnostics.filter(function (item) { return item.status === "ok"; }).length;

    return h(ShareContext.Provider, { value: shareMode }, h("div", { className: "newton-ops " + (shareMode ? "newton-ops--share " : "") + (focusMode ? "newton-ops--focus" : ""), role: "region", "aria-label": "Newton Operations" },
      shareMode ? h("div", { className: "newton-share-watermark", role: "status" }, "SANITIZED DEMO · NO LIVE OPERATIONAL DATA") : null,
      h("header", { className: "newton-hero" }, h("div", { className: "newton-hero__grid", "aria-hidden": "true" }),
        h("div", { className: "newton-hero__copy" }, h("div", { className: "newton-command-line" }, h("span", { className: "newton-command-line__mark" }, "N/O"), h("span", null, "PROFILE-SCOPED · READ-ONLY HERMES SOURCES")), h("h2", null, "Newton Operations"), h("p", null, "An explainable operations cockpit for gateway posture, active work, reliability, and durable decisions."),
          h("nav", { className: "newton-jump-nav", "aria-label": "Newton Operations sections" }, ["attention", "timeline", "kanban", "cron", "diagnostics", "journal"].map(function (anchor) { return h("a", { key: anchor, href: "#" + anchor }, anchor); }))),
        h("div", { className: "newton-hero__actions" },
          h(StatusPill, { value: viewHealth.status || stateOf(view.gateway || {}) }),
          h("div", { className: "newton-action-cluster" },
            h(Button, { type: "button", className: focusMode ? "is-active" : "", "aria-pressed": focusMode, onClick: function () { setFocusMode(!focusMode); }, title: "Keyboard shortcut: Alt+Shift+F" }, focusMode ? "Show all" : "Focus"),
            h(Button, { type: "button", className: shareMode ? "is-active" : "", "aria-pressed": shareMode, onClick: toggleShareMode, title: shareMode ? "Requires confirmation before showing live data" : "Keyboard shortcut: Alt+Shift+S" }, shareMode ? (exitShareArmed ? "Confirm live view" : "Exit share") : "Share mode"),
            h(Button, { type: "button", disabled: refreshing || shareMode, onClick: function () { loadData(true); }, title: "Keyboard shortcut: Alt+Shift+R" }, refreshing ? "Refreshing…" : "Refresh")),
          shareMode ? h("div", { className: "newton-share-actions" }, h(Button, { type: "button", onClick: copyShareSummary }, "Copy summary"), h(Button, { type: "button", onClick: function () { window.print(); } }, "Print / save")) : null,
          h("span", { className: "newton-hero__timestamp" }, shareMode ? "Sanitized demonstration data" : "Snapshot " + formatTime(view.generated_at)))),
      loadError ? h("div", { className: "newton-load-error", role: "alert" }, h("strong", null, "Partial refresh failure"), h("span", null, loadError), h(Button, { type: "button", onClick: function () { loadData(true); } }, "Retry")) : null,
      h("section", { className: "newton-metrics", "aria-label": "Operations summary" },
        h(Metric, { label: "Gateway", value: stateOf(view.gateway || {}), tone: toneOf(stateOf(view.gateway || {})), hint: number(view.gateway && view.gateway.active_agents, 0) + " active agents" }),
        h(Metric, { label: "Attention", value: attention.length, tone: attention.length ? "warning" : "good", hint: attention.length ? "explainable signals" : "clear" }),
        h(Metric, { label: "Active work", value: number(view.current_work && view.current_work.count, 0), hint: "Kanban + runtime" }),
        h(Metric, { label: "Cron reliability", value: averageReliability, tone: averageReliability === "100%" ? "good" : "warning", hint: "recent finished runs" }),
        h(Metric, { label: "Data sources", value: healthySources + "/" + diagnostics.length, tone: healthySources === diagnostics.length ? "good" : "warning", hint: "bounded read models" })),
      h("div", { className: "newton-dashboard" },
        h(GatewayPanel, { gateway: view.gateway, profile: view.profile }),
        h(AttentionPanel, { items: attention }),
        h(TimelinePanel, { allItems: allTimeline, items: filteredTimeline, source: timelineSource, query: timelineQuery, readOnly: shareMode, expanded: timelineExpanded, onToggle: function () { setTimelineExpanded(function (value) { return !value; }); }, onSource: setTimelineSource, onQuery: setTimelineQuery, searchRef: searchRef }),
        focusMode ? null : h(KanbanPanel, { section: view.kanban }),
        focusMode ? null : h(CronPanel, { section: view.cron, expanded: cronExpanded, onToggle: function () { setCronExpanded(function (value) { return !value; }); } }),
        focusMode ? null : h(RuntimePanel, { delegations: view.delegations, processes: view.processes }),
        focusMode ? null : h(SessionsPanel, { section: view.sessions }),
        focusMode ? null : h(DiagnosticsPanel, { section: view.diagnostics }),
        focusMode ? null : h(JournalPanel, { shareMode: shareMode, records: filteredRecords, allRecords: allRecords, query: journalQuery, statusFilter: journalStatus, onQuery: setJournalQuery, onStatusFilter: setJournalStatus, form: form, onForm: updateForm, onSubmit: submitJournal, onSeal: sealRecord, busy: journalBusy, busyRecord: busyRecord, notice: notice })),
      h("footer", { className: "newton-footer" }, h("span", null, shareMode ? "Sanitized demo" : "Adaptive 10s / 30s refresh"), h("span", { "aria-hidden": "true" }, "·"), h("span", null, "Pauses while hidden"), h("span", { "aria-hidden": "true" }, "·"), h("span", null, "Shortcuts use Alt+Shift: R refresh · F focus · S share · / search"))));
  }

  registry.register("newton-operations", NewtonOperationsPage);
})();
