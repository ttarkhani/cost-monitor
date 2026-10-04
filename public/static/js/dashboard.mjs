// Dashboard: fetches the API, renders with createElement/textContent only
// (no innerHTML with API data), and owns the single Chart.js instance.
import {
  RANGE_OPTIONS, OTHER_COLOR, alertProblems, alertViewModel, apiQuery, buildCalendarAxis,
  buildSearch, coverage, csvFilename, dayComparison, detectorPanel, formatDate, formatSignedUSD,
  formatUSD, formatUSDPrecise, formatPct, gapNotice, Y_AXIS_MIN_SUGGESTED_MAX, liveFallbackNotice, parseState, pluralize, serviceBreakdown, serviceColorMap,
  serviceValue, seriesPlan, staleNotice, toCSV, windowTotal,
} from './logic.mjs';

const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

// Set by the server; false on deployments where live mode is disabled (e.g. the public Vercel site).
const urlOptions = { liveEnabled: document.body.dataset.liveEnabled !== 'false' };
let state = parseState(window.location.search, urlOptions);
let chart = null;
let inflight = null;
let current = null; // what is on screen right now: { rows, synthetic, mode }

// ------------------------------------------------------------------ helpers

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (k === 'style') Object.assign(node.style, v);
    else node.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) {
    if (c !== null && c !== undefined && c !== false) node.append(c);
  }
  return node;
}

const SVG_NS = 'http://www.w3.org/2000/svg';
const ICON_PATHS = {
  alert: ['M8 1.5 15 14H1z', 'M8 6v3.5M8 11.5v.5'],
  check: ['M3 8.5 6.5 12 13 4.5'],
  clock: ['M8 1.75a6.25 6.25 0 1 0 0 12.5 6.25 6.25 0 0 0 0-12.5z', 'M8 4.5V8l2.5 1.5'],
  info: ['M8 1.75a6.25 6.25 0 1 0 0 12.5 6.25 6.25 0 0 0 0-12.5z', 'M8 7v4.5M8 4.75v.5'],
};

function icon(name) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 16 16');
  svg.setAttribute('width', '16');
  svg.setAttribute('height', '16');
  svg.setAttribute('aria-hidden', 'true');
  for (const d of ICON_PATHS[name]) {
    const p = document.createElementNS(SVG_NS, 'path');
    p.setAttribute('d', d);
    p.setAttribute('fill', 'none');
    p.setAttribute('stroke', 'currentColor');
    p.setAttribute('stroke-width', '1.6');
    p.setAttribute('stroke-linecap', 'round');
    p.setAttribute('stroke-linejoin', 'round');
    svg.append(p);
  }
  return svg;
}

async function fetchJSON(path, signal) {
  const res = await fetch(path, { signal, headers: { Accept: 'application/json' } });
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON body: reported below */ }
  if (!res.ok) throw new Error(body && typeof body.error === 'string' ? body.error : `HTTP ${res.status}`);
  if (!body || typeof body !== 'object' || !('data' in body)) throw new Error('Unexpected response shape');
  return body;
}

// ------------------------------------------------------------------ controls

function syncControls() {
  for (const b of document.querySelectorAll('[data-mode]')) {
    b.setAttribute('aria-pressed', String(b.dataset.mode === state.mode));
  }
  for (const b of document.querySelectorAll('[data-days]')) {
    b.setAttribute('aria-pressed', String(Number(b.dataset.days) === state.days));
  }
}

function setState(next) {
  const modeChanged = next.mode !== state.mode;
  state = { ...state, ...next };
  window.history.pushState(null, '', `${window.location.pathname}${buildSearch(state, urlOptions)}`);
  syncControls();
  // Never leave one mode's numbers on screen under the other mode's labels.
  if (modeChanged) resetView();
  load();
}

function bindControls() {
  for (const b of document.querySelectorAll('[data-mode]')) {
    b.addEventListener('click', () => { if (b.dataset.mode !== state.mode) setState({ mode: b.dataset.mode }); });
  }
  for (const b of document.querySelectorAll('[data-days]')) {
    const days = Number(b.dataset.days);
    if (!RANGE_OPTIONS.includes(days)) continue;
    b.addEventListener('click', () => { if (days !== state.days) setState({ days }); });
  }
  $('refresh-btn').addEventListener('click', () => load());
  $('retry-btn').addEventListener('click', () => load());
  $('export-btn').addEventListener('click', exportCSV);
  window.addEventListener('popstate', () => {
    const next = parseState(window.location.search, urlOptions);
    const modeChanged = next.mode !== state.mode;
    state = next;
    syncControls();
    if (modeChanged) resetView();
    load();
  });
}

// ------------------------------------------------------------------ banners

function setSyntheticBanner(show) {
  $('synthetic-banner').hidden = !show;
  document.title = show ? 'Cost Monitor · DEMO (synthetic data)' : 'Cost Monitor';
}

function setErrors(errors) {
  // errors: [{ what, message }]. Identical messages are grouped onto one line.
  const byMessage = new Map();
  for (const { what, message } of errors) byMessage.set(message, [...(byMessage.get(message) ?? []), what]);
  const banner = $('error-banner');
  const list = $('error-list');
  list.replaceChildren(...[...byMessage].map(([message, whats]) => el('li', { text: `${whats.join(', ')}: ${message}` })));
  banner.hidden = errors.length === 0;
}

// ------------------------------------------------------------------ stat cards

function setCard(id, { label, value, note, textValue = false }) {
  const card = $(id);
  if (label) card.querySelector('.stat-label').textContent = label;
  const v = card.querySelector('.stat-value');
  v.className = `stat-value${textValue ? ' is-text' : ''}`;
  v.textContent = value;
  card.querySelector('.stat-note').textContent = note ?? '';
}

function renderCards(rows) {
  if (!rows) {
    for (const id of ['card-latest', 'card-change', 'card-total', 'card-coverage']) {
      setCard(id, { value: 'Unavailable', note: 'Cost data failed to load.', textValue: true });
    }
    return;
  }
  if (!rows.length) {
    setCard('card-latest', { value: 'No data', note: 'No snapshots in this range.', textValue: true });
    setCard('card-change', { value: '—', note: 'Nothing to compare.' });
    setCard('card-total', { label: 'Total across recorded days', value: '—', note: '' });
    setCard('card-coverage', { value: '—', note: 'No snapshots in this range.' });
    return;
  }

  const cmp = dayComparison(rows);
  setCard('card-latest', { value: formatUSD(cmp.latest.total_cost), note: formatDate(cmp.latest.date) });

  if (cmp.kind === 'consecutive') {
    // Neutral ink on purpose: an ordinary increase is not an alarm; the detector panel decides that.
    setCard('card-change', { value: formatSignedUSD(cmp.delta),
      note: `vs ${formatDate(cmp.previous.date)} (${formatUSD(cmp.previous.total_cost)})` });
  } else if (cmp.kind === 'not_consecutive') {
    setCard('card-change', { value: 'No 1-day comparison', textValue: true,
      note: `Previous snapshot is ${pluralize(cmp.daysEarlier, 'day')} earlier (${formatDate(cmp.previous.date)}).` });
  } else {
    setCard('card-change', { value: '—', note: 'Only one recorded day in this range.' });
  }

  const cov = coverage(rows);
  setCard('card-total', { label: `Total across ${pluralize(cov.recorded, 'recorded day')}`,
    value: formatUSD(windowTotal(rows)),
    note: `${formatDate(rows[0].date, { short: true })} – ${formatDate(rows[rows.length - 1].date)}` });
  setCard('card-coverage', { value: `${cov.recorded} of ${cov.calendarDays}`,
    note: cov.missing ? `calendar days recorded · ${pluralize(cov.missing, 'day')} missing` : 'calendar days recorded · no gaps' });
}

// ------------------------------------------------------------------ detector panel

function stateBlock(kind, iconName, title, detail, extra = []) {
  return el('div', { class: `detector-state state-${kind}` }, icon(iconName),
    el('div', {}, el('p', { class: 'state-title', text: title }),
      detail ? el('p', { class: 'state-detail', text: detail }) : null, ...extra));
}

function renderDetector(alerts, status, alertsFailed) {
  const body = $('detector-body');
  const nodes = [];
  const meta = $('detector-meta');
  meta.textContent = status ? `${pluralize(status.valid_transitions, 'valid day-to-day change')} in the detection window` : '';

  if (alertsFailed) {
    nodes.push(stateBlock('unknown', 'info', 'Anomaly list unavailable',
      'The alerts request failed, so this panel cannot say whether anything is unusual.'));
  } else {
    const panel = detectorPanel(alerts, status);
    if (panel.kind === 'anomalies') {
      nodes.push(stateBlock('anomalies', 'alert', panel.title,
        'Day-over-day increases the detector flagged, newest first.'));
      const sorted = [...alerts].sort((a, b) => b.date.localeCompare(a.date)
        || (a.level === 'aggregate' ? -1 : 1));
      nodes.push(el('ul', { class: 'alert-list' }, sorted.map((a) => {
        const vm = alertViewModel(a);
        return el('li', { class: 'alert-row' },
          el('span', { class: 'alert-label' }, vm.label,
            el('span', { class: 'pill', text: vm.scope }),
            vm.isNew ? el('span', { class: 'pill pill-new', text: 'New service' }) : null),
          el('span', { class: 'alert-date', text: vm.dateText }),
          el('span', { class: 'alert-change', text: vm.change }),
          el('span', { class: 'alert-z', text: vm.zText, title: vm.zTitle, tabindex: '0',
            'aria-label': `${vm.zText}. ${vm.zTitle}` }));
      })));
    } else if (panel.kind === 'clear') {
      nodes.push(stateBlock('clear', 'check', panel.title, panel.detail));
    } else if (panel.kind === 'warming_up') {
      const pct = Math.round((panel.progress / panel.required) * 100);
      nodes.push(stateBlock('warming', 'clock', panel.title, panel.detail, [
        el('div', { class: 'progress', role: 'progressbar', 'aria-valuemin': '0',
          'aria-valuemax': String(panel.required), 'aria-valuenow': String(panel.progress),
          'aria-label': 'Baseline transitions collected' }, el('span', { style: { width: `${pct}%` } })),
        el('p', { class: 'progress-text', text: panel.progressText }),
      ]));
    } else {
      nodes.push(stateBlock('unknown', 'info', panel.title, panel.detail));
    }
  }

  const stale = staleNotice(status);
  if (stale) nodes.push(el('div', { class: 'notice notice-stale', role: 'note' }, icon('alert'), el('p', { text: stale })));

  const gaps = gapNotice(status);
  if (gaps) {
    nodes.push(el('div', { class: 'notice', role: 'note' }, icon('info'),
      el('div', {}, el('p', { text: gaps.text }), el('ul', {}, gaps.gaps.map((g) => el('li', { text: g }))))));
  }
  body.replaceChildren(...nodes);
}

// ------------------------------------------------------------------ chart

function showChartMessage(message) {
  const box = $('chart-empty');
  box.textContent = message;
  box.hidden = !message;
  $('cost-chart').hidden = Boolean(message);
}

function destroyChart() {
  if (chart) { chart.destroy(); chart = null; }
}

function renderChart(rows, alerts, colors, plan) {
  destroyChart();
  const canvas = $('cost-chart');
  if (!rows) {
    canvas.setAttribute('aria-label', 'Daily spend chart unavailable');
    showChartMessage('Cost data failed to load.');
    return;
  }
  if (!rows.length) {
    canvas.setAttribute('aria-label', 'Daily spend chart: no data in this range');
    showChartMessage('No snapshots recorded in this range.');
    return;
  }

  const axis = buildCalendarAxis(rows);
  const cov = coverage(rows);
  const flagged = new Map();
  for (const a of alerts ?? []) {
    const list = flagged.get(a.date) ?? [];
    list.push(a.level === 'service' ? a.service : 'Total spend');
    flagged.set(a.date, list);
  }
  canvas.setAttribute('aria-label', `Stacked bar chart of daily spend by service, ${formatDate(rows[0].date)} to `
    + `${formatDate(rows[rows.length - 1].date)}: ${pluralize(cov.recorded, 'recorded day')}, `
    + `${pluralize(cov.missing, 'day')} with no snapshot, ${pluralize(flagged.size, 'day')} with flagged anomalies. `
    + 'The same data is available in the table below the chart.');

  if (typeof window.Chart !== 'function') {
    showChartMessage('The chart library could not be loaded (CDN unreachable?). Every value is still in the table below.');
    $('chart-table').closest('details').open = true;
    return;
  }
  showChartMessage('');

  const surface = css('--surface');
  const datasets = plan.names.map((name) => ({
    type: 'bar',
    label: name,
    data: axis.map((d) => (d.row ? serviceValue(d.row, name, plan.folded) : null)),
    backgroundColor: colors.get(name),
    borderColor: surface,
    borderWidth: { top: 2 },
    borderSkipped: 'bottom',
    stack: 'spend',
    maxBarThickness: 36,
  }));
  if (!plan.names.length) {
    // Every recorded day is $0 with no service lines: still give each day a
    // (zero-height) element so hovering shows "$0.00 recorded" rather than nothing.
    datasets.push({ type: 'bar', label: 'Total', data: axis.map((d) => (d.row ? d.row.total_cost : null)),
      backgroundColor: css('--accent'), stack: 'spend', maxBarThickness: 36 });
  }
  if (cov.missing) {
    datasets.push({
      type: 'bar', label: 'No snapshot recorded', yAxisID: 'yGap', stack: 'gap',
      data: axis.map((d) => (d.row ? null : 1)), // full-height band on a hidden 0..1 axis, not a dollar value
      backgroundColor: 'rgba(255, 255, 255, 0.05)', borderColor: 'rgba(255, 255, 255, 0.18)',
      borderWidth: 1, borderDash: [4, 4], grouped: false, barPercentage: 1, categoryPercentage: 1,
    });
  }
  if (flagged.size) {
    // Marker sits a little above the bar top; its height is a position, not a value
    // (the tooltip shows which series were flagged, never this number).
    const lift = Math.max(...rows.map((r) => r.total_cost)) * 0.05;
    datasets.push({
      type: 'line', label: 'Anomaly flagged', stack: 'markers', order: -1,
      data: axis.map((d) => (d.row && flagged.has(d.date) ? d.row.total_cost + lift : null)),
      showLine: false, pointStyle: 'triangle', rotation: 180, pointRadius: 8, pointHoverRadius: 10,
      pointBackgroundColor: css('--critical'), pointBorderColor: surface, pointBorderWidth: 2,
      backgroundColor: css('--critical'), borderColor: css('--critical'),
    });
  }

  const ink = css('--ink-secondary');
  const muted = css('--ink-muted');
  chart = new window.Chart(canvas, {
    type: 'bar',
    data: { labels: axis.map((d) => formatDate(d.date, { short: true })), datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: reducedMotion.matches ? false : { duration: 300 },
      interaction: { mode: 'index', intersect: false },
      scales: {
        x: { stacked: true, grid: { display: false }, border: { color: css('--axis') },
             ticks: { color: muted, autoSkip: true, autoSkipPadding: 14, maxRotation: 0 } },
        y: { stacked: true, beginAtZero: true, suggestedMax: Y_AXIS_MIN_SUGGESTED_MAX, grid: { color: css('--grid') }, border: { display: false },
             ticks: { color: muted, callback: (v) => formatUSD(v) } },
        yGap: { display: false, min: 0, max: 1, stacked: false },
      },
      plugins: {
        legend: { position: 'bottom', labels: { color: ink, usePointStyle: true, boxWidth: 8, boxHeight: 8, padding: 16 } },
        tooltip: {
          backgroundColor: css('--surface-raised'), borderColor: css('--border-strong'), borderWidth: 1,
          titleColor: css('--ink'), bodyColor: ink, footerColor: css('--ink'), padding: 10,
          itemSort: (a, b) => (b.raw ?? 0) - (a.raw ?? 0),
          // Hide $0 service lines, except on a day whose recorded total is $0 (show that it was recorded).
          filter: (item) => item.dataset.stack !== 'spend' || item.raw > 0
            || (axis[item.dataIndex].row && axis[item.dataIndex].row.total_cost === 0),
          callbacks: {
            title: (items) => formatDate(axis[items[0].dataIndex].date),
            label: (item) => {
              if (item.dataset.stack === 'gap') return 'No snapshot recorded for this day (not $0)';
              if (item.dataset.stack === 'markers') return `Anomaly flagged: ${flagged.get(axis[item.dataIndex].date).join(', ')}`;
              return `${item.dataset.label}: ${formatUSDPrecise(item.raw)}`;
            },
            footer: (items) => {
              const row = axis[items[0].dataIndex].row;
              return row ? `Total: ${formatUSDPrecise(row.total_cost)}` : '';
            },
          },
        },
      },
    },
  });
}

function renderChartTable(rows, plan) {
  const table = $('chart-table');
  const names = plan ? plan.names : [];
  table.tHead.replaceChildren(el('tr', {},
    el('th', { scope: 'col', text: 'Date' }), el('th', { scope: 'col', class: 'num', text: 'Total' }),
    names.map((n) => el('th', { scope: 'col', class: 'num', text: n })),
    el('th', { scope: 'col', text: 'Note' })));
  const body = (rows ? buildCalendarAxis(rows) : []).map(({ date, row }) => el('tr', {},
    el('th', { scope: 'row', text: formatDate(date) }),
    el('td', { class: 'num', text: row ? formatUSD(row.total_cost) : '—' }),
    names.map((n) => el('td', { class: 'num', text: row ? formatUSD(serviceValue(row, n, plan.folded)) : '—' })),
    el('td', { class: row ? '' : 'muted', text: row ? '' : 'No snapshot recorded' })));
  table.tBodies[0].replaceChildren(...body);
}

// ------------------------------------------------------------------ breakdown

function renderBreakdown(rows, colors, plan) {
  const tbody = $('breakdown-table').tBodies[0];
  const note = $('breakdown-note');
  if (!rows || !rows.length) {
    tbody.replaceChildren(el('tr', {}, el('td', { colspan: '5', class: 'muted',
      text: rows ? 'No snapshots in this range.' : 'Cost data failed to load.' })));
    note.textContent = '';
    return;
  }
  const items = serviceBreakdown(rows);
  if (!items.length) {
    tbody.replaceChildren(el('tr', {}, el('td', { colspan: '5', class: 'muted',
      text: 'No service had non-zero spend in this range.' })));
  } else {
    tbody.replaceChildren(...items.map((s) => el('tr', {},
      el('th', { scope: 'row' }, el('span', { class: 'swatch', 'aria-hidden': 'true',
        style: { background: colors.get(s.name) ?? (plan.folded.includes(s.name) ? OTHER_COLOR : 'transparent') } }), s.name),
      el('td', { class: 'num', text: formatUSD(s.latest) }),
      el('td', { class: 'num', text: formatPct(s.share) }),
      el('td', { class: 'num', text: formatUSD(s.windowTotal) }),
      el('td', { class: `num${s.change === null ? ' muted' : ''}`, text: s.change === null ? 'n/a' : formatSignedUSD(s.change) }))));
  }
  const cmp = dayComparison(rows);
  note.textContent = cmp.kind === 'consecutive' ? ''
    : 'Change vs previous day is only shown when the previous snapshot is exactly one calendar day earlier.';
}

// ------------------------------------------------------------------ export

function exportCSV() {
  if (!current || !current.rows || !current.rows.length) return;
  const blob = new Blob([toCSV(current.rows, { synthetic: current.synthetic })], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = el('a', { href: url, download: csvFilename(current.mode, current.rows) });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

// ------------------------------------------------------------------ load cycle

function resetView() {
  current = null;
  destroyChart();
  setSyntheticBanner(state.mode === 'demo');
  for (const id of ['card-latest', 'card-change', 'card-total', 'card-coverage']) {
    const v = $(id).querySelector('.stat-value');
    v.className = 'stat-value';
    v.replaceChildren(el('span', { class: 'skeleton', text: ' ' }));
    $(id).querySelector('.stat-note').textContent = '';
  }
  $('detector-body').replaceChildren(el('p', { class: 'skeleton-line' }, el('span', { class: 'skeleton', text: ' ' })));
  $('detector-meta').textContent = '';
  $('chart-meta').textContent = '';
  showChartMessage('Loading…');
  $('chart-table').tHead.replaceChildren();
  $('chart-table').tBodies[0].replaceChildren();
  $('breakdown-table').tBodies[0].replaceChildren();
  $('breakdown-note').textContent = '';
  $('export-btn').disabled = true;
}

function setBusy(busy) {
  const main = $('main');
  main.setAttribute('aria-busy', String(busy));
  main.classList.toggle('is-loading', busy);
  $('refresh-btn').setAttribute('aria-busy', String(busy));
  $('retry-btn').disabled = busy;
}

async function load() {
  if (inflight) inflight.abort();
  const controller = new AbortController();
  inflight = controller;
  const requested = { ...state };
  const q = apiQuery(requested);
  const started = performance.now();
  setBusy(true);
  if (requested.mode === 'demo') setSyntheticBanner(true);

  const [costsR, alertsR, statusR] = await Promise.allSettled([
    fetchJSON(`/api/costs?${q}`, controller.signal),
    fetchJSON(`/api/alerts?${q}`, controller.signal),
    fetchJSON(`/api/detector-status?${q}`, controller.signal),
  ]);
  if (controller.signal.aborted) return; // a newer load() owns the screen now
  inflight = null;
  const clientMs = Math.round(performance.now() - started);

  const errors = [];
  const fail = (what, r) => errors.push({ what, message: r.reason && r.reason.message ? r.reason.message : 'request failed' });

  const costs = costsR.status === 'fulfilled' && Array.isArray(costsR.value.data) ? costsR.value : null;
  if (!costs) fail('Cost data', costsR.status === 'rejected' ? costsR : { reason: new Error('Unexpected response shape') });

  let alerts = null;
  if (alertsR.status === 'fulfilled' && Array.isArray(alertsR.value.data)) {
    const bad = alertsR.value.data.map(alertProblems).filter((p) => p.length);
    if (bad.length) {
      errors.push({ what: 'Alerts', message: `${bad.length} item(s) did not match the expected shape (${bad[0].join(', ')}); they are not shown.` });
    }
    alerts = alertsR.value.data.filter((a) => alertProblems(a).length === 0);
  } else {
    fail('Alerts', alertsR.status === 'rejected' ? alertsR : { reason: new Error('Unexpected response shape') });
  }

  const status = statusR.status === 'fulfilled' ? statusR.value.data : null;
  if (!status) fail('Detector status', statusR);

  // Label as synthetic if the request was demo OR any payload says so.
  const synthetic = requested.mode === 'demo'
    || [costsR, alertsR, statusR].some((r) => r.status === 'fulfilled' && r.value.synthetic === true);
  setSyntheticBanner(synthetic);

  const rows = costs ? costs.data : null;
  const plan = rows ? seriesPlan(rows) : null;
  const colors = plan ? serviceColorMap(plan.names) : new Map();
  current = { rows, synthetic, mode: requested.mode };

  renderCards(rows);
  renderDetector(alerts, status, alerts === null);
  renderChart(rows, alerts, colors, plan);
  renderChartTable(rows, plan);
  renderBreakdown(rows, colors, plan);
  $('export-btn').disabled = !(rows && rows.length);
  $('chart-meta').textContent = rows ? `Last ${requested.days} days · ${pluralize(rows.length, 'recorded day')}` : '';

  const meta = (costs && costs.meta) || (statusR.status === 'fulfilled' && statusR.value.meta) || null;
  if (meta && meta.history_days) $('history-days').textContent = String(meta.history_days);
  const source = meta ? `${meta.source}${synthetic ? ' (synthetic)' : ''}` : 'unavailable';
  const serverMs = meta && typeof meta.elapsed_ms === 'number' ? `${meta.elapsed_ms} ms` : 'n/a';
  $('status-line').textContent = `Source: ${source} · server ${serverMs} · client ${clientMs} ms · updated ${new Date().toLocaleTimeString()}`;

  setErrors(errors);
  setBusy(false);
}

// ------------------------------------------------------------------ boot

const fallback = liveFallbackNotice(window.location.search, urlOptions);
if (fallback) {
  $('mode-notice').textContent = fallback;
  $('mode-notice').hidden = false;
  // Make the address bar match what is actually shown.
  window.history.replaceState(null, '', `${window.location.pathname}${buildSearch(state, urlOptions)}`);
}
syncControls();
bindControls();
resetView();
load();
