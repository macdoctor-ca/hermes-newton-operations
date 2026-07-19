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

  const Card = C.Card || "section";
  const CardHeader = C.CardHeader || "header";
  const CardTitle = C.CardTitle || "h2";
  const CardContent = C.CardContent || "div";
  const Badge = C.Badge || "span";
  const Button = C.Button || "button";
  const Input = C.Input || "input";
  const Label = C.Label || "label";
  const Separator = C.Separator || "hr";

  const API = "/api/plugins/newton-operations";
  const EMPTY = [];

  function api(path, options) {
    return SDK.fetchJSON(API + path, options);
  }

  function isObject(value) {
    return !!value && typeof value === "object" && !Array.isArray(value);
  }

  function pick(source, keys, fallback) {
    if (!source) return fallback;
    for (let i = 0; i < keys.length; i += 1) {
      const value = source[keys[i]];
      if (value !== undefined && value !== null) return value;
    }
    return fallback;
  }

  function listFrom(value, nestedKeys) {
    if (Array.isArray(value)) return value;
    if (!isObject(value)) return EMPTY;
    const keys = nestedKeys || ["items", "records", "recent", "rows"];
    for (let i = 0; i < keys.length; i += 1) {
      if (Array.isArray(value[keys[i]])) return value[keys[i]];
    }
    return EMPTY;
  }

  function numberFrom(value, keys, fallback) {
    const raw = isObject(value) ? pick(value, keys, fallback) : fallback;
    const number = Number(raw);
    return Number.isFinite(number) ? number : fallback;
  }

  function countOf(value, itemKeys) {
    if (Array.isArray(value)) return value.length;
    if (!isObject(value)) return 0;
    const explicit = numberFrom(
      value,
      ["count", "total", "total_count", "active_count", "enabled_count"],
      Number.NaN
    );
    if (Number.isFinite(explicit)) return explicit;
    return listFrom(value, itemKeys).length;
  }

  function text(value, fallback) {
    if (value === undefined || value === null || value === "") return fallback || "—";
    if (typeof value === "string" || typeof value === "number") return String(value);
    if (typeof value === "boolean") return value ? "Yes" : "No";
    if (isObject(value)) {
      return text(pick(value, ["label", "name", "title", "status", "state"], null), fallback);
    }
    return fallback || "—";
  }

  function titleOf(item, fallback) {
    if (!isObject(item)) return text(item, fallback);
    return text(
      pick(item, ["title", "name", "label", "summary", "kind", "type", "id"], null),
      fallback
    );
  }

  function detailOf(item, fallback) {
    if (!isObject(item)) return fallback || "";
    return text(
      pick(item, ["detail", "description", "reason", "schedule", "source", "note", "outcome"], null),
      fallback || ""
    );
  }

  function statusOf(item, fallback) {
    if (typeof item === "string") return item;
    if (!isObject(item)) return fallback || "unknown";
    if (item.healthy === true || item.ok === true || item.available === true) return "healthy";
    if (item.healthy === false || item.ok === false || item.available === false) return "unavailable";
    if (item.enabled === true && !pick(item, ["status", "state", "outcome"], null)) return "enabled";
    if (item.enabled === false && !pick(item, ["status", "state", "outcome"], null)) return "paused";
    return text(pick(item, ["status", "state", "outcome", "health"], fallback), fallback || "unknown");
  }

  function toneOf(value) {
    const normalized = String(value || "").toLowerCase();
    if (/healthy|online|ready|running|active|enabled|complete|success|ok|sealed/.test(normalized)) return "good";
    if (/blocked|failed|error|critical|offline|dead|unavailable|overdue/.test(normalized)) return "critical";
    if (/warning|attention|stale|paused|waiting|degraded|pending|retrying|reconnecting/.test(normalized)) return "warning";
    return "neutral";
  }

  function formatTime(value) {
    if (value === undefined || value === null || value === "") return "Not reported";
    let date;
    if (typeof value === "number") {
      date = new Date(value < 100000000000 ? value * 1000 : value);
    } else {
      date = new Date(value);
    }
    if (Number.isNaN(date.getTime())) return text(value, "Not reported");
    return date.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  }

  function relativeTime(value) {
    if (value === undefined || value === null || value === "") return "";
    try {
      if (typeof value === "string" && SDK.utils && typeof SDK.utils.isoTimeAgo === "function") {
        return SDK.utils.isoTimeAgo(value);
      }
      if (SDK.utils && typeof SDK.utils.timeAgo === "function") {
        const number = Number(value);
        if (Number.isFinite(number)) return SDK.utils.timeAgo(number < 100000000000 ? number * 1000 : number);
      }
    } catch (_) {
      return formatTime(value);
    }
    return formatTime(value);
  }

  function joinMeta(values) {
    return values.filter(function (value) {
      return value !== undefined && value !== null && value !== "" && value !== "—";
    }).map(function (value) {
      return String(value);
    }).join(" · ");
  }

  function keyFor(item, index, prefix) {
    if (isObject(item)) {
      const key = pick(item, ["id", "record_id", "session_id", "task_id", "job_id", "name"], null);
      if (key !== null) return prefix + "-" + String(key);
    }
    return prefix + "-" + String(index);
  }

  function withKind(items, kind) {
    return items.map(function (item) {
      if (isObject(item)) return Object.assign({ _surface: kind }, item);
      return { _surface: kind, title: text(item, kind) };
    });
  }

  function sessionItems(snapshot) {
    const section = pick(snapshot, ["sessions", "recent_sessions", "session_activity"], null);
    return listFrom(section, ["items", "recent", "sessions", "rows"]);
  }

  function cronItems(snapshot) {
    const section = pick(snapshot, ["cron", "cron_jobs", "schedules"], null);
    return listFrom(section, ["items", "jobs", "recent", "rows"]);
  }

  function kanbanItems(snapshot) {
    const section = pick(snapshot, ["kanban", "board", "tasks"], null);
    const direct = listFrom(section, ["items", "tasks", "active", "rows"]);
    if (direct.length) return direct;
    if (!isObject(section)) return EMPTY;
    return []
      .concat(listFrom(section.running, ["items", "tasks"]))
      .concat(listFrom(section.blocked, ["items", "tasks"]))
      .concat(listFrom(section.ready, ["items", "tasks"]));
  }

  function runtimeItems(snapshot) {
    const delegations = listFrom(
      pick(snapshot, ["delegations", "agents", "subagents"], null),
      ["items", "active", "delegations", "rows"]
    );
    const processes = listFrom(
      pick(snapshot, ["processes", "background_processes", "runtimes"], null),
      ["items", "active", "processes", "rows"]
    );
    return withKind(delegations, "delegation").concat(withKind(processes, "process"));
  }

  function currentWorkItems(snapshot) {
    const section = pick(snapshot, ["current_work", "active_work", "work"], null);
    const direct = listFrom(section, ["items", "active", "work", "rows"]);
    if (direct.length) return direct;
    return withKind(kanbanItems(snapshot), "kanban")
      .concat(runtimeItems(snapshot))
      .slice(0, 8);
  }

  function attentionItems(snapshot, health) {
    const section = pick(snapshot, ["attention", "attention_items", "alerts"], null);
    const direct = listFrom(section, ["items", "alerts", "attention", "rows"]);
    const degraded = listFrom(
      pick(snapshot, ["degraded_components", "degraded", "component_warnings"], null),
      ["items", "components", "warnings"]
    );
    const healthDegraded = listFrom(
      pick(health, ["degraded_components", "degraded", "warnings"], null),
      ["items", "components", "warnings"]
    );
    return direct
      .concat(withKind(degraded, "component"))
      .concat(withKind(healthDegraded, "component"));
  }

  function journalItems(payload) {
    return listFrom(payload, ["records", "items", "journal", "rows"]);
  }

  function gatewayDetails(snapshot, health) {
    const gateway = pick(snapshot, ["gateway", "gateway_health"], null);
    if (isObject(gateway)) return gateway;
    const healthGateway = pick(health, ["gateway", "gateway_health"], null);
    if (isObject(healthGateway)) return healthGateway;
    return isObject(health) ? health : {};
  }

  function StatusPill(props) {
    const value = text(props.value, "unknown");
    const tone = props.tone || toneOf(value);
    return h(
      Badge,
      { className: "newton-status newton-status--" + tone },
      h("span", { className: "newton-status__dot", "aria-hidden": "true" }),
      props.label || value
    );
  }

  function Metric(props) {
    return h(
      "div",
      { className: "newton-metric" },
      h("span", { className: "newton-metric__label" }, props.label),
      h("strong", { className: "newton-metric__value" }, text(props.value, "0")),
      props.hint ? h("span", { className: "newton-metric__hint" }, props.hint) : null
    );
  }

  function SectionHeading(props) {
    return h(
      "div",
      { className: "newton-section-heading" },
      h("div", { className: "newton-section-heading__index", "aria-hidden": "true" }, props.index),
      h(
        "div",
        { className: "newton-section-heading__copy" },
        props.eyebrow ? h("span", { className: "newton-eyebrow" }, props.eyebrow) : null,
        h(CardTitle, { className: "newton-section-heading__title" }, props.title)
      ),
      props.meta ? h("div", { className: "newton-section-heading__meta" }, props.meta) : null
    );
  }

  function EmptyState(props) {
    return h(
      "div",
      { className: "newton-empty" },
      h("span", { className: "newton-empty__mark", "aria-hidden": "true" }, "—"),
      h("span", null, props.children)
    );
  }

  function OperationRow(props) {
    return h(
      "li",
      { className: "newton-row" },
      h("span", { className: "newton-row__rail newton-row__rail--" + toneOf(props.status), "aria-hidden": "true" }),
      h(
        "div",
        { className: "newton-row__body" },
        h(
          "div",
          { className: "newton-row__topline" },
          h("strong", { className: "newton-row__title" }, props.title),
          props.status ? h(StatusPill, { value: props.status }) : null
        ),
        props.detail ? h("p", { className: "newton-row__detail" }, props.detail) : null,
        props.meta ? h("span", { className: "newton-row__meta" }, props.meta) : null
      ),
      props.action || null
    );
  }

  function Panel(props) {
    return h(
      Card,
      { className: "newton-panel " + (props.className || "") },
      h(
        CardHeader,
        { className: "newton-panel__header" },
        h(SectionHeading, {
          index: props.index,
          eyebrow: props.eyebrow,
          title: props.title,
          meta: props.meta,
        })
      ),
      h(CardContent, { className: "newton-panel__content" }, props.children)
    );
  }

  function GatewayPanel(props) {
    const gateway = props.gateway;
    const status = statusOf(gateway, "unknown");
    const facts = [
      ["Profile", pick(gateway, ["profile", "profile_name"], null)],
      ["Uptime", pick(gateway, ["uptime", "uptime_human", "uptime_seconds"], null)],
      ["Scheduler", pick(gateway, ["scheduler", "cron_status"], null)],
      ["Last event", relativeTime(pick(gateway, ["last_event_at", "updated_at", "last_seen"], null))],
    ].filter(function (fact) { return fact[1] !== null && fact[1] !== ""; });

    return h(
      Panel,
      {
        className: "newton-panel--gateway",
        index: "01",
        eyebrow: "Control plane",
        title: "Gateway health",
        meta: h(StatusPill, { value: status }),
      },
      h(
        "div",
        { className: "newton-gateway" },
        h(
          "div",
          { className: "newton-gateway__signal newton-gateway__signal--" + toneOf(status) },
          h("span", { className: "newton-gateway__pulse", "aria-hidden": "true" }),
          h("div", null,
            h("strong", null, status === "unknown" ? "Signal pending" : text(status, "Signal pending")),
            h("span", null, "Authenticated dashboard path")
          )
        ),
        facts.length
          ? h("dl", { className: "newton-facts" }, facts.map(function (fact) {
              return h(React.Fragment, { key: fact[0] },
                h("dt", null, fact[0]),
                h("dd", null, text(fact[1], "—"))
              );
            }))
          : h(EmptyState, null, "Gateway details are not available yet.")
      )
    );
  }

  function AttentionPanel(props) {
    const items = props.items;
    return h(
      Panel,
      {
        className: "newton-panel--attention",
        index: "02",
        eyebrow: "Exceptions",
        title: "Needs attention",
        meta: items.length ? items.length + " open" : "Clear",
      },
      items.length
        ? h("ul", { className: "newton-attention-grid" }, items.slice(0, 8).map(function (item, index) {
            const status = statusOf(item, "attention");
            return h(OperationRow, {
              key: keyFor(item, index, "attention"),
              title: titleOf(item, "Operational notice"),
              detail: detailOf(item, "Review this signal when convenient."),
              status: status,
              meta: joinMeta([
                isObject(item) ? pick(item, ["component", "source", "_surface"], null) : null,
                isObject(item) ? relativeTime(pick(item, ["created_at", "updated_at", "at"], null)) : null,
              ]),
            });
          }))
        : h(
            "div",
            { className: "newton-clear-state" },
            h("span", { className: "newton-clear-state__glyph", "aria-hidden": "true" }, "✓"),
            h("div", null,
              h("strong", null, "No active exceptions"),
              h("p", null, "Native stores report no blocked, failed, or degraded work.")
            )
          )
    );
  }

  function WorkPanel(props) {
    const items = props.items;
    return h(
      Panel,
      {
        className: "newton-panel--work",
        index: "03",
        eyebrow: "In flight",
        title: "Current work",
        meta: items.length + " active",
      },
      items.length
        ? h("ul", { className: "newton-list" }, items.slice(0, 8).map(function (item, index) {
            const surface = isObject(item) ? pick(item, ["_surface", "kind", "type"], null) : null;
            return h(OperationRow, {
              key: keyFor(item, index, "work"),
              title: titleOf(item, "Active work"),
              detail: detailOf(item, ""),
              status: statusOf(item, "active"),
              meta: joinMeta([
                surface,
                isObject(item) ? pick(item, ["assignee", "profile", "owner"], null) : null,
                isObject(item) ? relativeTime(pick(item, ["started_at", "updated_at", "created_at"], null)) : null,
              ]),
            });
          }))
        : h(EmptyState, null, "No active work is reported across Kanban or background runtimes.")
    );
  }

  function SessionsPanel(props) {
    const items = props.items;
    return h(
      Panel,
      {
        index: "04",
        eyebrow: "Continuity",
        title: "Recent sessions",
        meta: props.total + " tracked",
      },
      items.length
        ? h("ul", { className: "newton-list newton-list--compact" }, items.slice(0, 6).map(function (item, index) {
            return h(OperationRow, {
              key: keyFor(item, index, "session"),
              title: titleOf(item, "Untitled session"),
              detail: "",
              status: statusOf(item, "recent"),
              meta: joinMeta([
                isObject(item) ? pick(item, ["source", "platform"], null) : null,
                isObject(item) ? pick(item, ["model", "model_name"], null) : null,
                isObject(item) ? relativeTime(pick(item, ["last_active", "updated_at", "created_at"], null)) : null,
              ]),
            });
          }))
        : h(EmptyState, null, "No recent session metadata is available.")
    );
  }

  function CronPanel(props) {
    const items = props.items;
    return h(
      Panel,
      {
        index: "05",
        eyebrow: "Cadence",
        title: "Cron schedule",
        meta: props.total + " jobs",
      },
      items.length
        ? h("ul", { className: "newton-list newton-list--compact" }, items.slice(0, 6).map(function (item, index) {
            return h(OperationRow, {
              key: keyFor(item, index, "cron"),
              title: titleOf(item, "Scheduled job"),
              detail: isObject(item) ? text(pick(item, ["schedule", "repeat", "expression"], null), "") : "",
              status: statusOf(item, "scheduled"),
              meta: joinMeta([
                isObject(item) ? relativeTime(pick(item, ["next_run_at", "next_run", "last_run_at"], null)) : null,
                isObject(item) && item.no_agent === true ? "deterministic" : null,
              ]),
            });
          }))
        : h(EmptyState, null, "No cron jobs are visible in the canonical schedule.")
    );
  }

  function KanbanPanel(props) {
    const items = props.items;
    return h(
      Panel,
      {
        index: "06",
        eyebrow: "Delivery",
        title: "Kanban flow",
        meta: props.total + " tasks",
      },
      items.length
        ? h("ul", { className: "newton-list newton-list--compact" }, items.slice(0, 6).map(function (item, index) {
            return h(OperationRow, {
              key: keyFor(item, index, "kanban"),
              title: titleOf(item, "Kanban task"),
              detail: "",
              status: statusOf(item, "todo"),
              meta: joinMeta([
                isObject(item) ? pick(item, ["assignee", "profile", "owner"], null) : null,
                isObject(item) ? pick(item, ["priority", "tenant", "board"], null) : null,
                isObject(item) ? relativeTime(pick(item, ["updated_at", "created_at"], null)) : null,
              ]),
            });
          }))
        : h(EmptyState, null, "No active Kanban tasks are visible.")
    );
  }

  function RuntimePanel(props) {
    const items = props.items;
    return h(
      Panel,
      {
        index: "07",
        eyebrow: "Execution",
        title: "Delegations & processes",
        meta: items.length + " running",
      },
      items.length
        ? h("ul", { className: "newton-list newton-list--compact" }, items.slice(0, 8).map(function (item, index) {
            return h(OperationRow, {
              key: keyFor(item, index, "runtime"),
              title: titleOf(item, text(item._surface, "Runtime")),
              detail: detailOf(item, ""),
              status: statusOf(item, "active"),
              meta: joinMeta([
                item._surface,
                pick(item, ["profile", "agent", "backend"], null),
                relativeTime(pick(item, ["started_at", "created_at", "updated_at"], null)),
              ]),
            });
          }))
        : h(EmptyState, null, "No delegated agents or background processes are running.")
    );
  }

  function JournalPanel(props) {
    return h(
      Panel,
      {
        className: "newton-panel--journal",
        index: "08",
        eyebrow: "Durable context",
        title: "Decision & outcome journal",
        meta: props.records.length + " records",
      },
      h(
        "div",
        { className: "newton-journal-layout" },
        h(
          "form",
          { className: "newton-journal-form", onSubmit: props.onSubmit },
          h(
            "div",
            { className: "newton-form-heading" },
            h("strong", null, "Record the signal, not the transcript"),
            h("p", null, "Capture a concise decision or completed outcome. Seal it when the record is final.")
          ),
          h(
            "div",
            { className: "newton-form-grid" },
            h(
              "div",
              { className: "newton-field newton-field--type" },
              h(Label, { htmlFor: "newton-journal-kind" }, "Record type"),
              h(
                "select",
                {
                  id: "newton-journal-kind",
                  className: "newton-select",
                  value: props.form.kind,
                  onChange: function (event) { props.onFormChange("kind", event.target.value); },
                },
                h("option", { value: "decision" }, "Decision"),
                h("option", { value: "outcome" }, "Outcome")
              )
            ),
            h(
              "div",
              { className: "newton-field newton-field--title" },
              h(Label, { htmlFor: "newton-journal-title" }, "Title"),
              h(Input, {
                id: "newton-journal-title",
                value: props.form.title,
                maxLength: 120,
                placeholder: "What was decided or completed?",
                onChange: function (event) { props.onFormChange("title", event.target.value); },
              })
            ),
            h(
              "div",
              { className: "newton-field newton-field--summary" },
              h(Label, { htmlFor: "newton-journal-summary" }, "Summary"),
              h("textarea", {
                id: "newton-journal-summary",
                className: "newton-textarea",
                value: props.form.summary,
                maxLength: 500,
                rows: 4,
                placeholder: "Short rationale, result, or follow-up — no prompts or transcript excerpts.",
                onChange: function (event) { props.onFormChange("summary", event.target.value); },
              })
            )
          ),
          h(
            "div",
            { className: "newton-form-actions" },
            h(Button, {
              type: "submit",
              disabled: props.submitting || !props.form.title.trim() || !props.form.summary.trim(),
              className: "newton-primary-action",
            }, props.submitting ? "Recording…" : "Add to journal"),
            h("span", { className: "newton-form-limit" }, props.form.summary.length + " / 500")
          ),
          props.notice
            ? h("div", {
                className: "newton-notice newton-notice--" + props.notice.tone,
                role: "status",
                "aria-live": "polite",
              }, props.notice.message)
            : null
        ),
        h(Separator, { className: "newton-journal-separator" }),
        h(
          "div",
          { className: "newton-journal-records" },
          h("div", { className: "newton-records-heading" },
            h("strong", null, "Latest records"),
            h("span", null, "Append-only projection")
          ),
          props.records.length
            ? h("ol", { className: "newton-records" }, props.records.slice(0, 10).map(function (record, index) {
                const recordId = pick(record, ["record_id", "id"], null);
                const sealed = record.sealed === true || String(record.status || "").toLowerCase() === "sealed";
                const kind = text(pick(record, ["category", "kind", "record_type", "type"], "record"), "record");
                return h(
                  "li",
                  { className: "newton-record", key: keyFor(record, index, "record") },
                  h("div", { className: "newton-record__marker", "aria-hidden": "true" }, String(index + 1).padStart(2, "0")),
                  h(
                    "div",
                    { className: "newton-record__body" },
                    h("div", { className: "newton-record__head" },
                      h("span", { className: "newton-record__kind" }, kind),
                      h(StatusPill, { value: sealed ? "sealed" : "open" })
                    ),
                    h("strong", { className: "newton-record__title" }, titleOf(record, "Journal record")),
                    h("p", { className: "newton-record__summary" }, text(pick(record, ["summary", "detail", "note"], null), "No summary")),
                    h("span", { className: "newton-record__time" }, formatTime(pick(record, ["created_at", "updated_at", "at"], null)))
                  ),
                  !sealed && recordId !== null
                    ? h(Button, {
                        type: "button",
                        outlined: true,
                        size: "sm",
                        className: "newton-seal-action",
                        disabled: props.sealingId === String(recordId),
                        onClick: function () { props.onSeal(recordId); },
                        "aria-label": "Seal journal record " + titleOf(record, String(recordId)),
                      }, props.sealingId === String(recordId) ? "Sealing…" : "Seal")
                    : null
                );
              }))
            : h(EmptyState, null, "No decisions or outcomes have been recorded yet.")
        )
      )
    );
  }

  function LoadingShell() {
    return h(
      "div",
      { className: "newton-loading", role: "status", "aria-live": "polite" },
      h("span", { className: "newton-loading__pulse", "aria-hidden": "true" }),
      h("div", null,
        h("strong", null, "Reading native operations stores"),
        h("p", null, "Assembling a sanitized snapshot without copying session content.")
      )
    );
  }

  function NewtonOperationsPage() {
    const [health, setHealth] = useState(null);
    const [snapshot, setSnapshot] = useState(null);
    const [records, setRecords] = useState([]);
    const [initialLoading, setInitialLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [loadError, setLoadError] = useState(false);
    const [lastRefresh, setLastRefresh] = useState(null);
    const [form, setForm] = useState({ kind: "decision", title: "", summary: "" });
    const [submitting, setSubmitting] = useState(false);
    const [sealingId, setSealingId] = useState(null);
    const [notice, setNotice] = useState(null);
    const mountedRef = useRef(false);
    const loadingRef = useRef(false);
    const requestRef = useRef(0);

    const load = useCallback(function (manual) {
      if (loadingRef.current) return Promise.resolve();
      loadingRef.current = true;
      const requestId = requestRef.current + 1;
      requestRef.current = requestId;
      if (manual && mountedRef.current) setRefreshing(true);

      return Promise.all([api("/health"), api("/snapshot"), api("/journal")])
        .then(function (payloads) {
          if (!mountedRef.current || requestRef.current !== requestId) return;
          setHealth(payloads[0] || {});
          setSnapshot(payloads[1] || {});
          setRecords(journalItems(payloads[2]));
          setLoadError(false);
          setLastRefresh(new Date());
        })
        .catch(function () {
          if (mountedRef.current && requestRef.current === requestId) setLoadError(true);
        })
        .finally(function () {
          loadingRef.current = false;
          if (!mountedRef.current || requestRef.current !== requestId) return;
          setInitialLoading(false);
          setRefreshing(false);
        });
    }, []);

    useEffect(function () {
      mountedRef.current = true;
      load(false);
      const intervalId = setInterval(function () { load(false); }, 15000);
      return function () {
        mountedRef.current = false;
        clearInterval(intervalId);
      };
    }, [load]);

    const view = useMemo(function () {
      const data = snapshot || {};
      const sessionSection = pick(data, ["sessions", "recent_sessions", "session_activity"], null);
      const cronSection = pick(data, ["cron", "cron_jobs", "schedules"], null);
      const kanbanSection = pick(data, ["kanban", "board", "tasks"], null);
      return {
        gateway: gatewayDetails(data, health || {}),
        attention: attentionItems(data, health || {}),
        work: currentWorkItems(data),
        sessions: sessionItems(data),
        sessionTotal: countOf(sessionSection, ["items", "recent", "sessions", "rows"]),
        cron: cronItems(data),
        cronTotal: countOf(cronSection, ["items", "jobs", "recent", "rows"]),
        kanban: kanbanItems(data),
        kanbanTotal: countOf(kanbanSection, ["items", "tasks", "active", "rows"]),
        runtimes: runtimeItems(data),
      };
    }, [snapshot, health]);

    function updateForm(field, value) {
      setForm(function (current) {
        return Object.assign({}, current, { [field]: value });
      });
      setNotice(null);
    }

    function submitJournal(event) {
      event.preventDefault();
      const title = form.title.trim();
      const summary = form.summary.trim();
      if (!title || !summary || submitting) return;
      setSubmitting(true);
      setNotice(null);
      api("/journal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: form.kind, title: title, summary: summary }),
      })
        .then(function () {
          if (!mountedRef.current) return null;
          setForm({ kind: form.kind, title: "", summary: "" });
          setNotice({ tone: "good", message: "Journal record added." });
          return api("/journal");
        })
        .then(function (payload) {
          if (mountedRef.current && payload) setRecords(journalItems(payload));
        })
        .catch(function () {
          if (mountedRef.current) {
            setNotice({ tone: "critical", message: "The journal record could not be added. Check the fields and try again." });
          }
        })
        .finally(function () {
          if (mountedRef.current) setSubmitting(false);
        });
    }

    function sealRecord(recordId) {
      if (recordId === undefined || recordId === null || sealingId !== null) return;
      const id = String(recordId);
      setSealingId(id);
      setNotice(null);
      api("/journal/" + encodeURIComponent(recordId) + "/seal", { method: "POST" })
        .then(function () {
          if (!mountedRef.current) return null;
          setNotice({ tone: "good", message: "Journal record sealed." });
          return api("/journal");
        })
        .then(function (payload) {
          if (mountedRef.current && payload) setRecords(journalItems(payload));
        })
        .catch(function () {
          if (mountedRef.current) {
            setNotice({ tone: "critical", message: "The journal record could not be sealed." });
          }
        })
        .finally(function () {
          if (mountedRef.current) setSealingId(null);
        });
    }

    const gatewayStatus = text(pick(view.gateway, ["state", "status"], "unknown"), "unknown");
    const generatedAt = snapshot && pick(snapshot, ["generated_at", "updated_at", "as_of"], null);
    const refreshLabel = refreshing ? "Refreshing…" : "Refresh now";

    return h(
      "div",
      { className: "newton-ops", role: "region", "aria-label": "Newton Operations", "aria-busy": initialLoading || refreshing },
      h(
        "header",
        { className: "newton-hero" },
        h("div", { className: "newton-hero__grid", "aria-hidden": "true" }),
        h(
          "div",
          { className: "newton-hero__copy" },
          h("div", { className: "newton-command-line" },
            h("span", { className: "newton-command-line__mark" }, "N/O"),
            h("span", null, "Native operations / sanitized telemetry")
          ),
          h("h2", null, "Newton Operations"),
          h("p", null, "A single, low-noise view of what Hermes is doing, what needs a decision, and what finished well enough to remember.")
        ),
        h(
          "div",
          { className: "newton-hero__actions" },
          h(StatusPill, { value: gatewayStatus, label: "Gateway " + gatewayStatus }),
          h(Button, {
            type: "button",
            outlined: true,
            onClick: function () { load(true); },
            disabled: refreshing,
            className: "newton-refresh",
            "aria-label": "Manual refresh",
          }, h("span", { className: refreshing ? "newton-refresh__icon is-spinning" : "newton-refresh__icon", "aria-hidden": "true" }, "↻"), refreshLabel),
          h("span", { className: "newton-hero__timestamp" },
            generatedAt ? "Snapshot " + formatTime(generatedAt) : (lastRefresh ? "Checked " + formatTime(lastRefresh) : "Awaiting first snapshot")
          )
        )
      ),
      loadError
        ? h(
            "div",
            { className: "newton-load-error", role: "alert" },
            h("strong", null, "Operations snapshot unavailable"),
            h("span", null, "The page will retry automatically; existing data remains visible."),
            h(Button, { type: "button", outlined: true, size: "sm", onClick: function () { load(true); } }, "Retry")
          )
        : null,
      initialLoading && !snapshot
        ? h(LoadingShell, null)
        : h(
            React.Fragment,
            null,
            h(
              "section",
              { className: "newton-metrics", "aria-label": "Operations summary" },
              h(Metric, { label: "Gateway", value: gatewayStatus, hint: "control plane" }),
              h(Metric, { label: "In flight", value: view.work.length, hint: "current work" }),
              h(Metric, { label: "Attention", value: view.attention.length, hint: view.attention.length ? "review signals" : "no exceptions" }),
              h(Metric, { label: "Schedules", value: view.cronTotal, hint: "cron jobs" }),
              h(Metric, { label: "Sessions", value: view.sessionTotal, hint: "recent metadata" })
            ),
            h(
              "section",
              { className: "newton-dashboard", "aria-label": "Operations detail" },
              h(GatewayPanel, { gateway: view.gateway }),
              h(AttentionPanel, { items: view.attention }),
              h(WorkPanel, { items: view.work }),
              h(SessionsPanel, { items: view.sessions, total: view.sessionTotal }),
              h(CronPanel, { items: view.cron, total: view.cronTotal }),
              h(KanbanPanel, { items: view.kanban, total: view.kanbanTotal }),
              h(RuntimePanel, { items: view.runtimes }),
              h(JournalPanel, {
                records: records,
                form: form,
                submitting: submitting,
                sealingId: sealingId,
                notice: notice,
                onFormChange: updateForm,
                onSubmit: submitJournal,
                onSeal: sealRecord,
              })
            ),
            h(
              "footer",
              { className: "newton-footer" },
              h("span", null, "Read-only native stores"),
              h("span", { "aria-hidden": "true" }, "·"),
              h("span", null, "Explicit journal writes only"),
              h("span", { "aria-hidden": "true" }, "·"),
              h("span", null, "15 second refresh cadence")
            )
          )
    );
  }

  registry.register("newton-operations", NewtonOperationsPage);
})();
