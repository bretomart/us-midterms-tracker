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

The GitHub Pages site ships a baseline snapshot produced by `.github/workflows/deploy.yml` via `export_static.py`.

The published page polls civicAPI v2 directly in the reader's browser every 60 seconds (free, CORS-open mirror of the AP live results feed). Data freshness no longer depends on continuous GitHub Actions rebuilds. The snapshot provides the closing-hours schedule, the baseline seat counts, and offline fallback data.

AP publishes no call time, so race calls are ordered by when the tracker first saw them called. The server keeps that ledger in `state/call_log.json`; the published page keeps the same ledger in `localStorage`, seeded from the snapshot, because it has no server. Calls already made when tracking began cannot be ordered and are reported without a time. The workflow caches `state/call_log.json` between runs so each build can stamp the calls it observed since the last one, and a build with no cache starts from the committed copy in `fixtures/call_log.json`, because a call time cannot be recovered from the feed.

Workflow runs occur on pushes to `main` and on a 6-hour schedule to refresh the fallback snapshot.
