# US Midterms Tracker

A real-time election night results aggregator, race call monitor, and exit poll analyzer for the 2026 U.S. Midterm Elections.

## Overview

The tracker consolidates election night returns across multiple authoritative sources without web scraping or API keys:
- **Associated Press (AP):** Ingests live metadata and vote progress feeds directly from `interactives.apelections.org` for House, Senate, and Governor races.
- **NBC News Decision Desk:** Consumes structured race calls and vote percentages from the NBC News Firecracker API v2.
- **Cross-Source Conflict Detection:** Compares AP and NBC calls in real time to highlight split calls, differing projections, or single-outlet calls.
- **NBC National Exit Polls:** Five-minute recurring polling of SSRS voter survey cross-tabs across demographic subsets and issues.
- **10 News Wire Feeds:** Live RSS monitoring across major news outlets.

## Architecture

- `ap_source.py`: Ingestion and normalization of AP election-results JSON.
- `nbc_source.py`: Ingestion and normalization of NBC Firecracker race calls.
- `aggregate.py`: Multi-source race tallying, chamber majority projections, and conflict detection.
- `exitpoll.py`: SSRS National Election Pool exit poll ingestion.
- `server.py`: Asynchronous multi-feed polling daemon with HTTP status dashboards.

## Running Tests

```bash
python3 -m unittest discover -v
```

## Deployment

The GitHub Pages site is a build-time snapshot produced by `.github/workflows/deploy.yml`: it pulls the live feeds, runs the tests, and exports static payloads via `export_static.py`.

GitHub's scheduler throttles best-effort cron triggers on high-frequency public workflows (observed here: 5 landed scheduled runs in two days against a `*/5` cron, none aligned to the grid), so the workflow is driven by `workflow_dispatch` instead:

- `./run_cron.sh` dispatches a build immediately and waits for it.
- `./run_cron.sh --once-if-idle` skips when a run is already active; safe to wire into a 5-minute timer such as `systemd-run --user --on-calendar='*:0/5' ./run_cron.sh --once-if-idle`.
- `./run_cron.sh --watch` loops in the foreground, firing on every 5-minute boundary; after a failed build it retries at most once every 30 minutes (the workflow fails on purpose during upstream feed outages, keeping the last good deployment live).
- The `schedule:` trigger in the workflow remains as a fallback for when the machine running this script is offline.
