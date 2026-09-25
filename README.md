# 📊 Cost Monitor

AWS cost monitoring and anomaly-alerting system, built on real billing data pulled from the AWS Cost Explorer API. Detects day-over-day cost anomalies using a statistical method (not a guessed threshold), both in aggregate and per individual AWS service, and alerts by real email the moment a scheduled daily job finds something — running autonomously on AWS Lambda + EventBridge, not dependent on a laptop being on.

This is a monitoring and alerting tool — it does not claim or estimate cost savings. If a genuine optimization is ever found and fixed in the account it monitors, the before/after numbers would be documented here. Until then, every number below describes the system's own verified behavior — load times, a real confusion matrix, a real Lambda invocation, a real received email — not money saved, and not invented.

## Architecture

```
AWS Cost Explorer API
        │
        ▼
run_fetch.py (manual)   ─or─   AWS Lambda, daily via EventBridge
        │                       both call the same backend.pipeline.run_daily_pipeline()
        ▼
    DynamoDB  (one item per account_id + date)
        │
        ├──▶ backend.alerts (modified z-score: aggregate + per-service)
        │           │
        │           ▼
        │       AWS SNS ──▶ real email alert
        │
        ▼
   Flask API (/api/costs, /api/alerts, /api/cache-stats)
        │      ↕ in-memory TTL cache
        ▼
  Dashboard (Chart.js)
```

## Features

- **Live billing data** — fetches real daily cost/usage data from AWS's [Cost Explorer API](https://docs.aws.amazon.com/aws-cost-management/latest/userguide/ce-what-is.html), grouped by service
- **Historical snapshots** — one snapshot per account per day in DynamoDB; 5 real days on record as of this writing, including a real 10-day gap the system correctly detected and excluded rather than let corrupt its own statistics (see Challenges)
- **Statistical anomaly detection** — a modified z-score (median + median absolute deviation, robust to small-sample outliers in a way a plain mean/stddev z-score isn't) replaces a naive fixed-threshold check, evaluated both in aggregate and per individual AWS service, so a spike in one service isn't masked by a drop in another
- **Real email alerting** — a genuine AWS SNS subscription. Confirmed via an actual email received in an inbox, not just an API call returning success
- **Serverless daily automation** — AWS Lambda + EventBridge run the full ingest → detect → alert pipeline once a day, independent of whether any machine is powered on. The manual `run_fetch.py` path still exists for on-demand runs and shares the exact same underlying code
- **Interactive dashboard** — stacked bar chart of spend by service over time, rendered with [Chart.js](https://www.chartjs.org/), served directly by Flask
- **In-memory caching** — short-TTL cache in front of DynamoDB reads, with real hit/miss tracking exposed via its own API endpoint
- **Live stats, everywhere** — dashboard load times, cache hit rate, a real synthetic confusion matrix, a real Lambda invocation's actual duration and memory use. Nothing in this project's numbers is invented

## Tech stack

| Layer | Tech |
|---|---|
| Backend | Python 3.14, Flask |
| Data source | AWS Cost Explorer API |
| Storage | DynamoDB (on-demand billing mode) |
| Anomaly detection | Modified z-score (median + MAD), pure Python (`statistics` module, no numpy) |
| Alerting | AWS SNS (email) |
| Automation | AWS Lambda + EventBridge (daily scheduled trigger) |
| IAM | Least-privilege execution role — scoped to exactly 4 permission sets, created automatically by the setup script |
| Caching | In-memory TTL cache |
| Frontend | Server-rendered HTML/CSS/vanilla JS, Chart.js (CDN) |

Configured against a single AWS account (whichever credentials `aws configure` points to, for local/manual use — see Known limitations for how the automated path differs). Cost Explorer provides daily-granularity billing data with a ~24–36 hour lag.

## Real metrics

Measured on this project, not estimated.

| Metric | Result |
|---|---|
| Full dashboard page load (client-measured, pre-caching) | 45–186ms across numerous real local reloads throughout the build |
| Cache-hit backend read time (`/api/costs` `meta.elapsed_ms`) | 0.0ms, confirmed via direct API response |
| Cache hit rate (early testing, small sample) | 33.3% (1 hit / 2 misses) |
| Anomaly detection — synthetic validation suite | 3/3 true positives, 0 false positives, 0 false negatives, across 5 scenarios (38 total judgments). Precision 1.000, recall 1.000, false positive rate 0.000 |
| Anomaly detection — real account data | Not yet activated: 3 of the 5 minimum valid consecutive-day deltas accumulated so far (needs 7 gap-free real days total; the real 10-day gap below doesn't count toward this) |
| Real AWS cost data ingested | 5 real days (2026-09-11 through 2026-09-24), including one real 10-day gap in ingestion, correctly detected and excluded from the statistical baseline rather than silently corrupting it |
| AWS Lambda invocation, verified end-to-end | Duration 518.77ms (1398ms billed, including cold-start init), 102MB of 256MB memory used. Real CloudWatch Logs and a real DynamoDB write confirmed, not just a returned success code |
| SNS alert delivery | Confirmed: a real test alert was received in a real inbox, subject and body matching exactly what the code generates |

**Anomaly detection — synthetic validation suite, in detail:**
- Stable baseline, single real spike, organic multi-day growth (should *not* be flagged, even though each day individually clears the dollar floor), near-zero free-tier-style noise with one real jump, and a real missed-ingestion gap followed by a real anomaly 4 days later — all correctly handled
- This is explicitly synthetic, hand-constructed ground truth — not real production incidents. A clean result here means the method is *correct on these known cases*, not a claim that it will be perfect on arbitrary future real data
- Real account data hasn't produced a genuine verdict yet simply because there isn't enough of it — the detector is built to say nothing rather than guess on too little history

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
For local/manual use, requires `ce:GetCostAndUsage`; `dynamodb:CreateTable`/`PutItem`/`Query`/`DescribeTable`; `sns:CreateTopic`/`Subscribe`/`Publish`/`ListSubscriptionsByTopic`; and `sts:GetCallerIdentity`.

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

**Enable real email alerts (optional):**
```bash
export ALERT_EMAIL=your_real_email@example.com
python setup_sns.py
```
Then check that inbox and click the confirmation link AWS sends — required before any alert will actually arrive. Verify with:
```bash
python test_alerting.py
```

**Automate with AWS Lambda + EventBridge (optional):**
```bash
mkdir -p lambda_package
cp lambda_handler.py lambda_package/
cp -r backend lambda_package/
rm -rf lambda_package/backend/__pycache__
cd lambda_package && zip -r ../lambda_deployment.zip . && cd ..
python setup_lambda_scheduler.py
```
This creates a dedicated, least-privilege IAM role (not root), packages and deploys the function, wires a daily EventBridge trigger, and immediately invokes it once for real to confirm it actually works end to end — rather than waiting a day to find out.

## API

| Endpoint | Description |
|---|---|
| `GET /` | Dashboard UI (server-rendered) |
| `GET /api/health` | Health check |
| `GET /api/costs` | Last 30 days of cost snapshots, by service (cached) |
| `GET /api/alerts` | Detected day-over-day cost anomalies, aggregate and per-service |
| `GET /api/cache-stats` | Real cache hit/miss counts and hit rate |

## Challenges & how they were solved

- **Chart.js failed to load, no obvious clue at first glance** — the CDN URL pinned a version (`4.4.4`) that was never published to cdnjs, returning a silent 404. Root-caused via browser console (`Chart is not defined`) and confirmed the actual published versions directly from cdnjs's own listing before pinning to a real one (`4.4.1`).
- **Chart rendered at a different size on every reload** — Chart.js locks in an aspect ratio at creation time rather than a fixed pixel size, so small differences in when the container's width is measured produced visibly different proportions between loads. Fixed with a fixed-height wrapper and `maintainAspectRatio: false`.
- **`ModuleNotFoundError` running the ingestion script directly** — Python resolves imports relative to the directory a script runs from, not the project root. Fixed by keeping `backend/` as pure importable modules, with root-level entry points (`run_fetch.py`, `lambda_handler.py`) as the things actually meant to run.
- **A naive `mad == 0` check let floating-point noise through** — comparing a statistic to exact zero is unsafe: decimal subtraction (e.g. `6.30 - 5.00`) doesn't always land on a clean value, leaving a residual as small as `1e-15` instead of `0.0`. That residual slipped past the check and blew up a z-score calculation into astronomical, meaningless numbers. Fixed with an epsilon-based comparison — caught by actually running the synthetic validation suite, not by code review alone.
- **Fixing that bug revealed a second, hidden one** — the zero-variance fallback's own boundary check (`today_dev > max_dev`) had the identical float-comparison fragility, producing a real false positive on a scenario specifically designed to prove the method *doesn't* flag normal growth. Fixed by applying the same epsilon-buffer principle there too, then re-validating the full suite from zero to confirm both fixes actually held together.
- **A real 10-day gap in ingestion history would have silently corrupted the detector's baseline** — `run_fetch.py` was run manually and sporadically during development, not daily, creating a genuine gap between two real stored snapshots. The original code treated any two list-adjacent entries as one calendar day apart; a 10-day jump misread as a 1-day jump would skew every future statistical comparison. Fixed by parsing real calendar dates and excluding any non-consecutive-day transition from both evaluation and the historical baseline — while still surfacing it explicitly, not hiding it.
- **A freshly created Lambda function can't be invoked immediately** — `create_function` returns before AWS finishes provisioning the function, so an immediate `invoke()` call correctly throws `ResourceConflictException` with the function still `Pending`. Fixed using boto3's real `function_active_v2` / `function_updated_v2` waiters, which poll the function's actual live state rather than guessing at a fixed sleep duration.
- **A Lambda deployment package silently missing one file** — a packaging step ran before `backend/pipeline.py` existed, producing `Runtime.ImportModuleError: No module named 'backend.pipeline'` only once actually invoked in AWS. Diagnosed precisely from the zip's own file listing, not guesswork, and fixed with a clean rebuild.
- **The dashboard quietly fell out of sync with a backend change** — after the detection method switched from a percent-based threshold to a z-score, the frontend's alert renderer was never updated to match, still reading a field (`increase_pct`) that no longer existed on most anomaly records. Caught by a deliberate audit before it ever misfired live, and verified fixed by injecting a real anomaly payload directly into the running dashboard's console.

## Known limitations

- Local development and manual runs (`aws configure`) still use AWS root credentials. The automated, scheduled execution path is meaningfully better: it runs under a separate, purpose-built IAM role scoped to exactly the 4 permission sets it needs (Cost Explorer read, this one DynamoDB table, this one SNS topic, STS), created automatically by `setup_lambda_scheduler.py`. A full production deployment would still move the local/manual path off root too.
- Detection constants (`Z_THRESHOLD=3.5`, `MIN_WINDOW=5`, `MIN_ABS_INCREASE=$1.00`, `MAD_EPSILON=1e-6`) and cache TTL (60s) are hardcoded, not exposed as runtime config.
- The historical baseline used for detection grows unbounded rather than using a fixed rolling window (e.g. the last 30/60 days only) — fine at the current data volume, worth revisiting once months of real history accumulate.
- Per-service anomaly detection has been proven correct on real stored data and one synthetic scenario, but hasn't yet been run through the same systematic 5-scenario confusion-matrix suite that aggregate-level detection has.
- EventBridge's *unattended* daily trigger — as opposed to a manual/verification invoke — hasn't been directly observed firing on its own yet as of this writing. The rule, target, and invoke permission are all confirmed correctly configured, and AWS's own mechanics mean it should fire on schedule, but that specific claim is still pending its first real, hands-off occurrence.
- Single AWS account only — no consolidated billing / multi-account support.
- Runs on Flask's built-in dev server, not a production WSGI server — this applies to the dashboard-viewing experience only; the actual scheduled ingestion pipeline runs on real AWS Lambda infrastructure, not Flask.
- Cache is in-memory and single-process — would need Redis to survive a restart or run across multiple processes.
- Cost Explorer's ~24–36h billing lag means the dashboard is never fully real-time.