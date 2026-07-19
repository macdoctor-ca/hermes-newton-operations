---
product: Newton Operations
surface: Hermes authenticated dashboard plugin
route: /operations
visual_posture: operational, dense, calm
---

# Newton Operations design specification

## Information hierarchy

1. **System posture** — one glance: healthy, busy, or attention needed; generated time; refresh control.
2. **Primary counters** — gateway agents, active work, scheduled jobs, blocked/failed items.
3. **Now** — in-flight agents, delegations, processes, and cron executions.
4. **Attention** — only actionable failures or blocked work; no decorative warning noise.
5. **Work queue and sessions** — compact lists with status, source, and recency.
6. **Decision journal** — recent decisions/outcomes plus a small explicit-entry form.

## Visual rules

- Match Hermes's existing compact navigation and content density.
- Follow the observed Hermes Teal vocabulary: monospace/letter-spaced uppercase micro-labels, cream primary controls, thin low-contrast borders, dark teal surfaces, restrained rounded corners, and compact 12–14 px supporting text. Resolve all of these through host components and variables rather than copying literal colors.
- Keep the main page airy while individual cards remain information-dense; the current Kanban page uses generous section separation and tight card interiors.
- Use the host design-system components when available; native elements are fallback only.
- Use host theme variables for every color and border. No hardcoded color literals.
- Prefer short labels and aligned metrics over large decorative cards.
- Use status dots and restrained badges; colour must never be the only status signal.
- Keep operational IDs de-emphasized or omit them entirely.
- Empty states should explain that there is no active work, not imply a loading failure.
- Degraded components should name the unavailable source without exposing raw exceptions.

## Layout

- Wide: four metric cards, then two-column sections with `Now/Attention` prominent.
- Medium: two metric cards per row, sections stack as needed.
- Narrow: one column; controls remain at least 40 px tall; horizontal overflow prohibited.
- Lists cap visible items and remain scan-friendly; the backend also bounds response size.

## Interaction

- Poll every 15 seconds and show the last successful refresh time.
- Manual refresh is always available and disabled while loading.
- Polling stops when the component unmounts.
- Journal creation is explicit; validation errors stay near the form.
- Sealing a record is a local, reversible-in-history state transition and never modifies Hermes memory.
- Links to Cron, Kanban, or Sessions use existing dashboard routes.

## Accessibility

- Semantic headings and sections.
- Text labels accompany status indicators.
- Form fields have visible labels.
- Buttons expose disabled/loading states.
- Focus styles come from host components/theme.
- Motion is unnecessary; honour reduced-motion by avoiding animation beyond host defaults.
