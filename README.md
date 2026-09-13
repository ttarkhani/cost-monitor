# 📊 Cost Monitor

AWS cost monitoring and anomaly-alerting dashboard, built on real billing data pulled from the AWS Cost Explorer API. Tracks daily spend by service, stores historical snapshots in DynamoDB, and flags day-over-day cost spikes that cross a configurable threshold.

This is a monitoring and alerting tool — it does not claim or estimate cost savings. If a genuine optimization is ever found and fixed in the account it monitors, the before/after numbers would be documented here. Until then, the metrics below describe the tool's own behavior (load times, cache performance, alert accuracy), not money saved.

## Features

- **Live billing data** — fetches real daily cost/usage data from AWS's [Cost Explorer API](https://docs.aws.amazon.com/aws-cost-management/latest/userguide/ce-what-is.html), grouped by service
- **Historical snapshots** — stores one snapshot per account per day in DynamoDB, so spend history persists and grows over time
- **Anomaly alerts** — flags day-over-day cost increases that cross a configurable percentage *and* dollar-amount threshold, filtering out normal small fluctuations
- **Interactive dashboard** — stacked bar chart of spend by service over time, rendered with [Chart.js](https://www.chartjs.org/), served directly by Flask
- **In-memory caching** — short-TTL cache in front of DynamoDB reads, with real hit/miss tracking exposed via its own API endpoint
- **Live stats** — real, currently-measured numbers (load times, cache hit rate, ingestion status), not invented figures

## Tech stack

| Layer | Tech |
|---|---|
| Backend | Python 3.14, Flask |
| Data source | AWS Cost Explorer API |
| Storage | DynamoDB (on-demand billing mode) |
| Caching | In-memory TTL cache |
| Frontend | Server-rendered HTML/CSS/vanilla JS, Chart.js (CDN) |

Configured against a single AWS account (whichever credentials `aws configure` points to). Cost Explorer provides daily-granularity billing data with a ~24–36 hour lag — see Known limitations.

## Real metrics

Measured on this project, not estimated.

| Metric | Result |
|---|---|
| Full dashboard page load (client-measured, pre-caching) | 45–186ms across 5 real local reloads |
| Cache-hit backend read time (`/api/costs` `meta.elapsed_ms`) | 0.0ms, confirmed via direct API response |
| Cache hit rate (early testing, small sample) | 33.3% (1 hit / 2 misses) |
| Anomaly detection, validated against test data | 1/1 true positive, 0 false positives |
| Real AWS cost data ingested | 0 days — Cost Explorer still indexing on this account |

**Anomaly detection validated against test data:**
- $5.20 → $5.35 (+2.9%) correctly left unflagged — below both thresholds
- $5.35 → $9.80 (+83.2%, a new service appearing) correctly flagged
- Thresholds (40% increase AND $1.00 minimum) are intentionally conservative, to avoid false alarms on small free-tier fluctuations

All ingestion, storage, alerting, and caching logic is built and tested against the Cost Explorer API's actual current responses — including its real `AccessDeniedException` (before enabling) and `DataUnavailableException` (while indexing) failure states — and will start storing real multi-day billing history with no code changes once AWS finishes indexing this account.

## Setup

**Requirements:** Python 3.10+ (tested on 3.14.7), an AWS account

```bash
git clone https://github.com/ttarkhani/cost-monitor.git
cd cost-monitor
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**Configure AWS credentials:**
```bash
aws configure
```
Requires `ce:GetCostAndUsage`, `dynamodb:CreateTable`/`PutItem`/`Query`/`DescribeTable`, and `sts:GetCallerIdentity`.

**Enable Cost Explorer** (one-time, per AWS account): Billing and Cost Management → Cost Explorer → Enable. Can take up to 24 hours to finish indexing on a new account before it returns data.

**Create the table and pull a day of data:**
```bash
python setup_dynamodb.py
python run_fetch.py     # pulls yesterday's finalized costs — Cost Explorer has a ~24–36h billing lag
```

**Run the dashboard:**
```bash
python app.py
```
Open `http://127.0.0.1:5001`.

## API

| Endpoint | Description |
|---|---|
| `GET /` | Dashboard UI (server-rendered) |
| `GET /api/health` | Health check |
| `GET /api/costs` | Last 30 days of cost snapshots, by service (cached) |
| `GET /api/alerts` | Detected day-over-day cost anomalies |
| `GET /api/cache-stats` | Real cache hit/miss counts and hit rate |

## Challenges & how they were solved

- **Chart.js failed to load, no obvious clue at first glance** — the CDN URL pinned a version (`4.4.4`) that was never published to cdnjs, returning a silent 404. Root-caused via browser console (`Chart is not defined`) and confirmed the actual published versions directly from cdnjs's own listing before pinning to a real one (`4.4.1`).
- **Chart rendered at a different size on every reload** — Chart.js locks in an aspect ratio at creation time rather than a fixed pixel size, so small differences in when the container's width is measured produced visibly different chart proportions between loads. Fixed by giving the chart a fixed-height wrapper and setting `maintainAspectRatio: false`.
- **`ModuleNotFoundError` running the ingestion script directly** — Python resolves imports relative to the directory a script is run from, not the project root, so running a script *inside* `backend/` broke its own `from backend.db import ...` line. Fixed by keeping `backend/` as pure importable modules only, with a root-level entry point (`run_fetch.py`) as the thing actually meant to be run.
- **Cost Explorer's real indexing delay on a new AWS account** — enabling Cost Explorer returns `AccessDeniedException` before enabling, then `DataUnavailableException` for hours afterward while AWS indexes the account. The ingestion script is built and tested against these actual real API failure states, not assumed to always succeed.

## Known limitations

- Uses AWS root credentials in this local dev setup — a production deployment would use a scoped IAM user instead
- Alert thresholds (40% / $1.00) and cache TTL (60s) are hardcoded constants, not exposed as config
- Single AWS account only — no consolidated billing / multi-account support
- Runs on Flask's built-in dev server, not a production WSGI server
- Cache is in-memory and single-process — would need Redis to survive a restart or run across multiple processes
- Cost Explorer's ~24–36h billing lag means the dashboard is never fully real-time