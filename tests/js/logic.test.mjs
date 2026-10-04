// node --test tests/js/   (no npm packages)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  ALERT_REQUIRED_FIELDS, OTHER_LABEL, SERIES_COLORS, addDays, alertProblems, alertViewModel,
  apiQuery, buildCalendarAxis, buildSearch, coverage, csvFilename, dayComparison, daysBetween,
  detectorPanel, formatDate, formatSignedUSD, formatUSD, formatUSDPrecise, gapNotice, parseState, serviceBreakdown,
  serviceColorMap, serviceValue, seriesPlan, staleNotice, toCSV, windowTotal, Y_AXIS_MIN_SUGGESTED_MAX,
} from '../../static/js/logic.mjs';

// SYNTHETIC demo-mode API responses recorded by test_contract.py.
const fixture = JSON.parse(readFileSync(new URL('../fixtures/api_demo_contract.json', import.meta.url)));

const row = (date, services) => ({
  date, services, total_cost: Object.values(services).reduce((a, b) => a + b, 0),
});

// ------------------------------------------------------------------ formatting

test('formatUSD: exact zero is $0.00, values that would round to $0.00 are <$0.01', () => {
  assert.equal(formatUSD(0), '$0.00');
  assert.equal(formatUSD(9e-10), '<$0.01'); // real S3 line item on 2026-10-03
  assert.equal(formatUSD(0.004), '<$0.01');
  assert.equal(formatUSD(0.0049999), '<$0.01');
  assert.equal(formatUSD(0.005), '$0.01'); // rounds up to a cent, so it is shown as one
  assert.equal(formatUSD(0.01), '$0.01');
  assert.equal(formatUSD(12.345), '$12.35');
  assert.equal(formatUSD(1234.567), '$1,234.57');
  assert.equal(formatUSD(-0.5), '−$0.50');
  assert.equal(formatUSD(-12.345), '−$12.35');
  assert.equal(formatUSD(-9e-10), '−<$0.01');
  assert.equal(formatUSD(null), '—');
  assert.equal(formatUSD(NaN), '—');
});

test('formatUSDPrecise keeps full precision for sub-cent values (tooltips)', () => {
  assert.equal(formatUSDPrecise(9e-10), '<$0.01 ($0.0000000009)');
  assert.equal(formatUSDPrecise(0.004), '<$0.01 ($0.004)');
  assert.equal(formatUSDPrecise(0.0049999), '<$0.01 ($0.0049999)');
  assert.equal(formatUSDPrecise(-9e-10), '−<$0.01 (−$0.0000000009)');
  assert.equal(formatUSDPrecise(0), '$0.00');
  assert.equal(formatUSDPrecise(0.01), '$0.01');
  assert.equal(formatUSDPrecise(12.345), '$12.35');
  assert.equal(formatUSDPrecise(null), '—');
});

test('formatSignedUSD: "no change" for zero, signed <$0.01 for sub-cent changes', () => {
  assert.equal(formatSignedUSD(0), 'no change');
  assert.equal(formatSignedUSD(9e-10), '+<$0.01');
  assert.equal(formatSignedUSD(-9e-10), '−<$0.01');
  assert.equal(formatSignedUSD(0.004), '+<$0.01');
  assert.equal(formatSignedUSD(0.005), '+$0.01');
  assert.equal(formatSignedUSD(8.16), '+$8.16');
  assert.equal(formatSignedUSD(-0.5), '−$0.50');
  assert.equal(formatSignedUSD(-12.345), '−$12.35');
  assert.equal(formatSignedUSD(null), '—');
});

test('y-axis floor is $1.00 and leaves demo-scale data alone', () => {
  assert.equal(Y_AXIS_MIN_SUGGESTED_MAX, 1);
  // suggestedMax only raises the axis maximum; demo days are all well above it.
  const demoMax = Math.max(...fixture.costs.data.map((r) => r.total_cost));
  assert.ok(demoMax > Y_AXIS_MIN_SUGGESTED_MAX);
});

test('formatDate never shifts the day through local time zones', () => {
  assert.equal(formatDate('2026-10-03'), 'Oct 3, 2026');
  assert.equal(formatDate('2026-01-01', { short: true }), 'Jan 1');
  assert.equal(formatDate(null), '—');
});

// ------------------------------------------------------------------ dates and axis

test('date arithmetic is UTC and handles month/year/leap boundaries', () => {
  assert.equal(addDays('2026-12-31', 1), '2027-01-01');
  assert.equal(addDays('2028-02-28', 1), '2028-02-29');
  assert.equal(daysBetween('2026-03-07', '2026-03-09'), 2); // across a US DST change
});

test('calendar axis has one slot per calendar day and null for missing days', () => {
  const rows = [row('2026-09-30', { A: 1 }), row('2026-10-01', { A: 2 }), row('2026-10-04', { A: 3 })];
  const axis = buildCalendarAxis(rows);
  assert.deepEqual(axis.map((d) => d.date), ['2026-09-30', '2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04']);
  assert.deepEqual(axis.map((d) => d.row === null), [false, false, true, true, false]);
  assert.deepEqual(buildCalendarAxis([]), []);
});

test('coverage counts recorded vs calendar days', () => {
  const rows = [row('2026-09-30', {}), row('2026-10-04', {})];
  assert.deepEqual(coverage(rows), { recorded: 2, calendarDays: 5, missing: 3 });
  assert.deepEqual(coverage([]), { recorded: 0, calendarDays: 0, missing: 0 });
});

// ------------------------------------------------------------------ deltas

test('day comparison only gives a delta for consecutive days', () => {
  assert.equal(dayComparison([]).kind, 'empty');
  assert.equal(dayComparison([row('2026-10-01', { A: 1 })]).kind, 'no_previous');
  const gap = dayComparison([row('2026-10-01', { A: 1 }), row('2026-10-04', { A: 5 })]);
  assert.equal(gap.kind, 'not_consecutive');
  assert.equal(gap.daysEarlier, 3);
  assert.equal('delta' in gap, false);
  const ok = dayComparison([row('2026-10-03', { A: 1 }), row('2026-10-04', { A: 5 })]);
  assert.equal(ok.kind, 'consecutive');
  assert.equal(ok.delta, 4);
});

test('service breakdown: share of latest day, range total, change only when consecutive', () => {
  const rows = [row('2026-10-03', { A: 1, B: 1 }), row('2026-10-04', { A: 3, B: 1 })];
  const [a, b] = serviceBreakdown(rows);
  assert.deepEqual(a, { name: 'A', latest: 3, share: 0.75, windowTotal: 4, change: 2 });
  assert.equal(b.change, 0);
  const gapped = serviceBreakdown([row('2026-10-01', { A: 1 }), row('2026-10-04', { A: 3 })]);
  assert.equal(gapped[0].change, null);
  const zero = serviceBreakdown([row('2026-10-04', {})]);
  assert.deepEqual(zero, []);
  assert.equal(windowTotal(rows), 6);
});

// ------------------------------------------------------------------ colors

test('service colors follow the name, not the rank or the set size', () => {
  const a = serviceColorMap(['Amazon EC2', 'Amazon S3', 'Amazon RDS']);
  const b = serviceColorMap(['Amazon S3', 'Amazon EC2', 'Amazon RDS']);
  assert.deepEqual([...a.entries()].sort(), [...b.entries()].sort());
  const colors = [...serviceColorMap(['a', 'b', 'c', 'd', 'e', 'f', 'g']).values()];
  assert.equal(new Set(colors).size, SERIES_COLORS.length, 'no duplicate colors while slots remain');
  for (const c of colors) assert.ok(SERIES_COLORS.includes(c));
});

test('more services than color slots fold the smallest into Other', () => {
  const services = Object.fromEntries(Array.from({ length: 10 }, (_, i) => [`S${i}`, 10 - i]));
  const plan = seriesPlan([row('2026-10-04', services)]);
  assert.equal(plan.names.length, SERIES_COLORS.length);
  assert.equal(plan.names.at(-1), OTHER_LABEL);
  assert.deepEqual(plan.folded, ['S6', 'S7', 'S8', 'S9']);
  assert.equal(serviceValue(row('2026-10-04', services), OTHER_LABEL, plan.folded), 4 + 3 + 2 + 1);
});

// ------------------------------------------------------------------ alert contract

test('contract: every alert in the recorded API fixture has the fields the UI reads', () => {
  assert.ok(fixture.alerts.data.length > 0);
  for (const a of fixture.alerts.data) {
    assert.deepEqual(alertProblems(a), [], JSON.stringify(a));
    const vm = alertViewModel(a);
    for (const v of Object.values(vm)) {
      assert.ok(!String(v).includes('undefined') && !String(v).includes('NaN'), `${vm.key}: ${v}`);
    }
  }
});

test('contract: a payload missing a field is reported, not silently rendered', () => {
  const a = { ...fixture.alerts.data[0] };
  delete a.modified_z;
  assert.deepEqual(alertProblems(a), ['missing modified_z']);
  const svc = fixture.alerts.data.find((x) => x.level === 'service');
  const noNew = { ...svc };
  delete noNew.is_new;
  assert.deepEqual(alertProblems(noNew), ['missing is_new']);
  assert.deepEqual(alertProblems({ ...a, modified_z: null, level: 'region' }), ['unknown level region']);
  assert.deepEqual(alertProblems({ ...fixture.alerts.data[0], delta: '8.16' }), ['delta not a number']);
  assert.ok(ALERT_REQUIRED_FIELDS.includes('modified_z'));
  assert.ok(!ALERT_REQUIRED_FIELDS.includes('increase_pct'), 'removed field must not come back');
});

test('contract: costs and status payloads have the shape the dashboard reads', () => {
  for (const r of fixture.costs.data) {
    assert.equal(typeof r.date, 'string');
    assert.equal(typeof r.total_cost, 'number');
    assert.equal(typeof r.services, 'object');
  }
  assert.equal(typeof fixture.costs.meta.source, 'string'); // elapsed_ms is stripped when recording
  const s = fixture.detector_status.data;
  for (const k of ['state', 'valid_transitions', 'required_baseline', 'evaluated_transitions', 'gaps',
    'latest_snapshot_date', 'days_since_latest', 'stale']) assert.ok(k in s, k);
  for (const name of ['costs', 'alerts', 'detector_status']) assert.equal(fixture[name].synthetic, true);
});

test('alert view model: new service and zero-variance rows', () => {
  const svcNew = fixture.alerts.data.find((a) => a.is_new === true);
  const vm = alertViewModel(svcNew);
  assert.equal(vm.isNew, true);
  assert.match(vm.change, /^New service: \$/);
  assert.equal(vm.zText, 'no z-score');
  const agg = alertViewModel(fixture.alerts.data.find((a) => a.level === 'aggregate'));
  assert.equal(agg.label, 'Total spend');
  assert.match(agg.zText, /^z = \d+\.\d$/);
  assert.match(agg.zTitle, /robust standard deviations above the typical day-to-day change/);
});

// ------------------------------------------------------------------ detector panel

test('detector panel distinguishes anomalies, all-clear, and warming up', () => {
  const status = fixture.detector_status.data;
  assert.equal(detectorPanel(fixture.alerts.data, status).kind, 'anomalies');
  assert.equal(detectorPanel([], status).kind, 'clear');
  const warming = detectorPanel([], { ...status, state: 'warming_up', valid_transitions: 3,
    evaluated_transitions: 0, required_baseline: 5 });
  assert.equal(warming.kind, 'warming_up');
  assert.equal(warming.progressText, '3 of 5 baseline transitions');
  const full = detectorPanel([], { ...status, state: 'warming_up', valid_transitions: 5, evaluated_transitions: 0 });
  assert.match(full.detail, /next consecutive-day snapshot/);
  assert.equal(detectorPanel([], null).kind, 'unknown', 'no status must never read as all-clear');
});

test('gap and stale notices', () => {
  const status = fixture.detector_status.data;
  const g = gapNotice(status);
  assert.match(g.text, /^1 ingestion gap \(2 days with no snapshot\)/);
  assert.deepEqual(g.gaps, ['Sep 6 → Sep 9: 2 days missing']);
  assert.equal(gapNotice({ gaps: [] }), null);
  assert.equal(staleNotice(status), null);
  assert.match(staleNotice({ stale: true, latest_snapshot_date: '2026-09-28', days_since_latest: 6 }), /6 days old/);
});

// ------------------------------------------------------------------ URL state

test('URL state round-trips and rejects unknown values', () => {
  assert.deepEqual(parseState(''), { mode: 'live', days: 30 });
  assert.deepEqual(parseState('?mode=demo&days=7'), { mode: 'demo', days: 7 });
  assert.deepEqual(parseState('?mode=evil&days=999'), { mode: 'live', days: 30 });
  assert.equal(buildSearch({ mode: 'live', days: 30 }), '');
  assert.equal(buildSearch({ mode: 'demo', days: 60 }), '?mode=demo&days=60');
  assert.equal(apiQuery({ mode: 'demo', days: 7 }), 'mode=demo&days=7');
});

// ------------------------------------------------------------------ CSV

test('CSV export labels synthetic data, escapes cells, and names demo files', () => {
  const rows = [row('2026-10-04', { 'Amazon EC2': 1.5, '=HYPERLINK("x")': 0.25 })];
  const demo = toCSV(rows, { synthetic: true }).split('\r\n');
  assert.match(demo[0], /SYNTHETIC/);
  assert.equal(demo[1], `date,total_cost_usd,"'=HYPERLINK(""x"")",Amazon EC2`);
  assert.equal(demo[2], '2026-10-04,1.75,0.25,1.5');
  assert.doesNotMatch(toCSV(rows, { synthetic: false }), /SYNTHETIC/);
  const tiny = toCSV([row('2026-10-03', { 'Amazon Simple Storage Service': 9e-10 })], { synthetic: false });
  assert.equal(tiny.split('\r\n')[1], '2026-10-03,9e-10,9e-10', 'CSV keeps full precision');
  assert.equal(csvFilename('demo', rows), 'cost-monitor-demo-synthetic-2026-10-04_to_2026-10-04.csv');
  assert.equal(csvFilename('live', rows), 'cost-monitor-live-2026-10-04_to_2026-10-04.csv');
});
