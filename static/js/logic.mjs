// Pure view logic for the dashboard: no DOM, no fetch, no Chart.js.
// Imported by dashboard.mjs in the browser and by tests/js/*.test.mjs
// under `node --test`, so everything here must stay side-effect free.

export const MIN_BASELINE_FALLBACK = 5;
export const RANGE_OPTIONS = [7, 30, 60];
export const DEFAULT_STATE = { mode: 'live', days: 30 };

// Categorical slots (dark-surface steps), validated as an ordered set against
// the chart surface with the dataviz palette validator. Order matters. Red is
// deliberately left out: it is reserved for anomaly markers.
export const SERIES_COLORS = ['#3987e5', '#d95926', '#199e70', '#c98500',
                              '#d55181', '#008300', '#9085e9'];
export const OTHER_COLOR = '#6b6b66';
export const OTHER_LABEL = 'Other services';

// ---------------------------------------------------------------- formatting

const usd2 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD',
  minimumFractionDigits: 2, maximumFractionDigits: 2 });
const usdSmall = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD',
  minimumFractionDigits: 2, maximumFractionDigits: 4 });

/** Dollars. Sub-cent non-zero amounts keep up to 4 decimals so $0.004 never reads as $0.00. */
export function formatUSD(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const abs = Math.abs(value);
  return (abs > 0 && abs < 0.01 ? usdSmall : usd2).format(value);
}

export function formatSignedUSD(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  if (value === 0) return formatUSD(0);
  return (value > 0 ? '+' : '−') + formatUSD(Math.abs(value));
}

export function formatPct(fraction) {
  if (fraction === null || fraction === undefined || !Number.isFinite(fraction)) return '—';
  return `${(fraction * 100).toFixed(1)}%`;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** '2026-10-03' -> 'Oct 3, 2026' (or 'Oct 3' when short). Never goes through local time zones. */
export function formatDate(iso, { short = false } = {}) {
  if (!iso) return '—';
  const [y, m, d] = iso.split('-').map(Number);
  return short ? `${MONTHS[m - 1]} ${d}` : `${MONTHS[m - 1]} ${d}, ${y}`;
}

export function pluralize(n, one, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

// ---------------------------------------------------------------- dates (UTC)

function toUTC(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return Date.UTC(y, m - 1, d);
}

export function addDays(iso, n) {
  return new Date(toUTC(iso) + n * 86400000).toISOString().slice(0, 10);
}

export function daysBetween(a, b) {
  return Math.round((toUTC(b) - toUTC(a)) / 86400000);
}

// ---------------------------------------------------------------- series

/**
 * One entry per calendar day from the first to the last recorded date.
 * A day without a snapshot has row === null: the chart shows no bar for it,
 * never a $0 bar.
 */
export function buildCalendarAxis(rows) {
  if (!rows.length) return [];
  const byDate = new Map(rows.map((r) => [r.date, r]));
  const first = rows[0].date;
  const span = daysBetween(first, rows[rows.length - 1].date);
  const axis = [];
  for (let i = 0; i <= span; i += 1) {
    const date = addDays(first, i);
    axis.push({ date, row: byDate.get(date) ?? null });
  }
  return axis;
}

export function coverage(rows) {
  if (!rows.length) return { recorded: 0, calendarDays: 0, missing: 0 };
  const calendarDays = daysBetween(rows[0].date, rows[rows.length - 1].date) + 1;
  return { recorded: rows.length, calendarDays, missing: calendarDays - rows.length };
}

export function windowTotal(rows) {
  return rows.reduce((sum, r) => sum + r.total_cost, 0);
}

/**
 * Latest day vs the snapshot before it. delta is only given when the
 * previous snapshot is exactly one calendar day earlier.
 */
export function dayComparison(rows) {
  if (!rows.length) return { kind: 'empty' };
  const latest = rows[rows.length - 1];
  if (rows.length === 1) return { kind: 'no_previous', latest };
  const previous = rows[rows.length - 2];
  const daysEarlier = daysBetween(previous.date, latest.date);
  if (daysEarlier !== 1) return { kind: 'not_consecutive', latest, previous, daysEarlier };
  return { kind: 'consecutive', latest, previous, daysEarlier,
           delta: latest.total_cost - previous.total_cost };
}

function hashName(name) {
  let h = 2166136261;
  for (let i = 0; i < name.length; i += 1) {
    h ^= name.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/**
 * Stable color per service NAME, not per rank: each name prefers the slot
 * its hash points at, and collisions probe to the next free slot in
 * alphabetical order of names. Toggling the range only changes a color if
 * a colliding service enters or leaves the view.
 */
export function serviceColorMap(names) {
  const map = new Map();
  const used = new Set();
  for (const name of [...names].sort()) {
    if (name === OTHER_LABEL) { map.set(name, OTHER_COLOR); continue; }
    let slot = hashName(name) % SERIES_COLORS.length;
    for (let i = 0; i < SERIES_COLORS.length && used.has(slot); i += 1) {
      slot = (slot + 1) % SERIES_COLORS.length;
    }
    used.add(slot);
    map.set(name, SERIES_COLORS[slot]);
  }
  return map;
}

/**
 * Service names to plot, largest window total first. With more services
 * than color slots, the smallest are folded into one "Other services" series.
 */
export function seriesPlan(rows, maxSeries = SERIES_COLORS.length) {
  const totals = new Map();
  for (const r of rows) {
    for (const [name, cost] of Object.entries(r.services)) {
      totals.set(name, (totals.get(name) ?? 0) + cost);
    }
  }
  const names = [...totals.keys()].sort((a, b) => totals.get(b) - totals.get(a) || a.localeCompare(b));
  if (names.length <= maxSeries) return { names, folded: [] };
  return { names: [...names.slice(0, maxSeries - 1), OTHER_LABEL], folded: names.slice(maxSeries - 1) };
}

export function serviceValue(row, name, folded) {
  if (name === OTHER_LABEL) return folded.reduce((s, n) => s + (row.services[n] ?? 0), 0);
  return row.services[name] ?? 0;
}

/** Per-service table: latest-day dollars and share, window total, change only when consecutive. */
export function serviceBreakdown(rows) {
  if (!rows.length) return [];
  const cmp = dayComparison(rows);
  const latest = rows[rows.length - 1];
  const names = new Set(rows.flatMap((r) => Object.keys(r.services)));
  return [...names].map((name) => {
    const latestCost = latest.services[name] ?? 0;
    const total = rows.reduce((s, r) => s + (r.services[name] ?? 0), 0);
    return {
      name,
      latest: latestCost,
      share: latest.total_cost > 0 ? latestCost / latest.total_cost : null,
      windowTotal: total,
      change: cmp.kind === 'consecutive' ? latestCost - (cmp.previous.services[name] ?? 0) : null,
    };
  }).sort((a, b) => b.latest - a.latest || b.windowTotal - a.windowTotal || a.name.localeCompare(b.name));
}

// ---------------------------------------------------------------- alerts contract

// Fields the dashboard reads from each /api/alerts item. If the backend
// stops sending one, alertProblems() reports it instead of the UI quietly
// rendering "undefined" (which is what happened once with increase_pct).
export const ALERT_REQUIRED_FIELDS = ['level', 'service', 'date', 'previous_date', 'previous_cost',
  'current_cost', 'delta', 'modified_z', 'status', 'flagged', 'window_size', 'day_index'];

export function alertProblems(alert) {
  if (alert === null || typeof alert !== 'object') return ['not an object'];
  const problems = ALERT_REQUIRED_FIELDS.filter((k) => !(k in alert)).map((k) => `missing ${k}`);
  if (alert.level !== 'aggregate' && alert.level !== 'service') problems.push(`unknown level ${alert.level}`);
  if (alert.level === 'service' && !('is_new' in alert)) problems.push('missing is_new');
  for (const k of ['previous_cost', 'current_cost', 'delta']) {
    if (k in alert && typeof alert[k] !== 'number') problems.push(`${k} not a number`);
  }
  if ('modified_z' in alert && alert.modified_z !== null && typeof alert.modified_z !== 'number') {
    problems.push('modified_z not a number or null');
  }
  return problems;
}

export const Z_EXPLANATION = 'How many robust standard deviations above the typical day-to-day change '
  + 'this increase is (modified z-score, from the median and median absolute deviation of earlier '
  + 'consecutive-day changes). Flagged at 3.5 or more, and only for increases of at least $1.00.';
export const ZERO_VARIANCE_EXPLANATION = 'Earlier day-to-day changes were all identical, so no z-score '
  + 'can be computed; flagged because this increase is larger than any earlier change and at least $1.00.';

export function alertViewModel(alert) {
  const label = alert.level === 'service' ? alert.service : 'Total spend';
  const isNew = alert.level === 'service' && alert.is_new === true;
  return {
    key: `${alert.level}|${alert.service ?? ''}|${alert.date}`,
    label,
    scope: alert.level === 'service' ? 'Service' : 'Total',
    date: alert.date,
    dateText: formatDate(alert.date),
    isNew,
    change: isNew
      ? `New service: ${formatUSD(alert.current_cost)}`
      : `${formatUSD(alert.previous_cost)} → ${formatUSD(alert.current_cost)} (${formatSignedUSD(alert.delta)})`,
    zText: alert.modified_z === null ? 'no z-score' : `z = ${alert.modified_z.toFixed(1)}`,
    zTitle: alert.modified_z === null ? ZERO_VARIANCE_EXPLANATION : Z_EXPLANATION,
  };
}

/**
 * The detector panel has three distinct states plus "unknown" (status could
 * not be loaded). "clear" is only possible when the detector is active, so
 * "nothing unusual" is never shown for "not enough data".
 */
export function detectorPanel(alerts, status) {
  if (alerts && alerts.length) {
    return { kind: 'anomalies', title: `${pluralize(alerts.length, 'anomaly', 'anomalies')} in this range` };
  }
  if (!status) {
    return { kind: 'unknown', title: 'Detector status unavailable',
             detail: 'No anomalies were returned, but the detector status could not be loaded, so this is not an all-clear.' };
  }
  const required = status.required_baseline ?? MIN_BASELINE_FALLBACK;
  if (status.state === 'active') {
    return { kind: 'clear', title: 'Detector active: nothing unusual in this range',
             detail: `${pluralize(status.evaluated_transitions, 'day-to-day change')} evaluated against a baseline of earlier consecutive days.` };
  }
  const progress = Math.min(status.valid_transitions, required);
  const detail = progress >= required
    ? 'Baseline complete. The next consecutive-day snapshot will be the first one evaluated.'
    : `Needs ${required} day-to-day changes between consecutive calendar days before it can judge one. Gaps in ingestion do not count.`;
  return { kind: 'warming_up', title: 'Detector warming up: not enough history to judge yet',
           detail, progress, required, progressText: `${progress} of ${required} baseline transitions` };
}

export function gapNotice(status) {
  if (!status || !status.gaps || !status.gaps.length) return null;
  const missing = status.gaps.reduce((s, g) => s + g.days, 0);
  return {
    text: `${pluralize(status.gaps.length, 'ingestion gap')} (${pluralize(missing, 'day')} with no snapshot) in the detection window. Changes across a gap are not evaluated.`,
    gaps: status.gaps.map((g) => `${formatDate(g.from, { short: true })} → ${formatDate(g.to, { short: true })}: ${pluralize(g.days, 'day')} missing`),
  };
}

export function staleNotice(status) {
  if (!status || !status.stale) return null;
  return `Ingestion looks stale: the latest snapshot (${formatDate(status.latest_snapshot_date)}) is ${pluralize(status.days_since_latest, 'day')} old. The daily job may not be running.`;
}

// ---------------------------------------------------------------- URL state

export function parseState(search) {
  const params = new URLSearchParams(search);
  const mode = params.get('mode') === 'demo' ? 'demo' : 'live';
  const days = Number(params.get('days'));
  return { mode, days: RANGE_OPTIONS.includes(days) ? days : DEFAULT_STATE.days };
}

export function buildSearch(state) {
  const params = new URLSearchParams();
  if (state.mode !== DEFAULT_STATE.mode) params.set('mode', state.mode);
  if (state.days !== DEFAULT_STATE.days) params.set('days', String(state.days));
  const s = params.toString();
  return s ? `?${s}` : '';
}

export function apiQuery(state) {
  return `mode=${encodeURIComponent(state.mode)}&days=${encodeURIComponent(state.days)}`;
}

// ---------------------------------------------------------------- CSV

function csvCell(value) {
  if (typeof value === 'number') return String(value);
  const s = String(value);
  // Quote when needed; prefix formula-looking text so spreadsheets don't execute it.
  const safe = /^[=+\-@\t\r]/.test(s) ? `'${s}` : s;
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

export function toCSV(rows, { synthetic }) {
  const names = [...new Set(rows.flatMap((r) => Object.keys(r.services)))].sort();
  const lines = [];
  if (synthetic) lines.push(csvCell('# SYNTHETIC DEMO DATA - not real AWS billing data'));
  lines.push(['date', 'total_cost_usd', ...names].map(csvCell).join(','));
  for (const r of rows) {
    lines.push([r.date, r.total_cost, ...names.map((n) => r.services[n] ?? 0)].map(csvCell).join(','));
  }
  return `${lines.join('\r\n')}\r\n`;
}

export function csvFilename(mode, rows) {
  const range = rows.length ? `${rows[0].date}_to_${rows[rows.length - 1].date}` : 'empty';
  return `cost-monitor-${mode === 'demo' ? 'demo-synthetic' : 'live'}-${range}.csv`;
}
