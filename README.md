# US Midterms Tracker

A single-screen dashboard for the November 3, 2026 US midterm elections. It pulls live vote tallies, race calls, the poll-closing schedule, and wire coverage into one page, published on GitHub Pages and also runnable locally against the upstream feeds directly.

Accuracy drives the design. Every number carries its source and its age, and sources that disagree are shown side by side instead of being averaged.

## What it shows

- **Race board:** every Senate, House, governor, and ballot-measure row the feed carries, with reporting percentage, standing, candidate votes, the closing hour for that jurisdiction, and any call the feed has published.
- **Closing waves:** one card per distinct closing minute, split into the point where a jurisdiction's first precincts report and the point where it is fully closed.
- **Control arithmetic:** seats held before the election, seats not up this cycle, and how many seats each party needs for a majority in each chamber.
- **Wire coverage:** headlines from ten RSS providers (MS NOW, CNN, Fox, NBC, NPR, PBS, CBS, ABC, Politico, The Hill) with per-provider status and latency.
- **Coverage and provenance:** which sources were ingested, which were rejected and why, and the rules applied to the numbers.

## Data sources

Results come from **The Associated Press**, the outlet every US network and newspaper sources its race calls from. AP News publishes the numbers behind its results page as plain JSON on `interactives.apelections.org`, and the CDN answers any request that carries an AP News referer, so the pull needs no key and no HTML scraping:

| Endpoint | Purpose |
| :--- | :--- |
| `data-live/2026-11-03/results/national/metadata.json` | One record per race: office, state, seat, candidate roster, closing time, `raceCallStatus` |
| `data-live/2026-11-03/results/national/progress.json` | Live counts: votes per candidate, percent of the expected vote counted, the winner flag AP sets when it calls a race |

The adapter in `ap_source.py` rewrites both into the raw race shape the rest of the code already consumes, keeps only Senate, House, governor, and ballot-measure races, and never infers a call: a race counts as called only where AP has flagged a winner.

**civicAPI v2** (`https://civicapi.org/api/v2`) is the fallback. It is free, needs no key, and sends permissive CORS headers, but it has been timing out under election-night load. When AP fails the four civicAPI calls (`race/search` for general and statewide races, plus the national House and Senate rollups) are tried instead, and the header names whichever source answered.

Closing hours come from state election office documents and statutes. Starting-line composition (seats held before the election) comes from Ballotpedia pages current as of November 3, 2026, cross-checked against AP's own results where the feed carries it.

Sources that were rejected, with the observed failure: the AP Elections REST API (key-gated, paid; the interactive feed is the public surface of the same numbers), Decision Desk HQ (`votes.decisiondeskHQ.com` returned HTTP 429, API paid), and the NEP/Edison exit polls and AP VoteCast (no reachable host: DNS failures and HTTP 403). No public machine-readable exit-poll crosstab feed exists, so the dashboard states that rather than inventing a panel.

## Prerequisites

Python 3.10 or newer. Nothing else: the server, the adapter, and the tests use only the standard library.

## Project layout

| File / Directory | Description |
| :--- | :--- |
| `run.py` | Entry point. Starts the server on port 8080, or `$PORT` if set. |
| `server.py` | HTTP server, payload assembly, upstream polling, and the RSS fetcher. |
| `aggregate.py` | Normalises races, tallies seats, projects control, and detects feed-versus-baseline conflicts. |
| `baseline.py` | Starting-line composition and majority thresholds for each chamber. |
| `schedule.py` | Poll-closing schedule by jurisdiction, closing waves, and the schedule's own caveats. |
| `ap_source.py` | Reads AP's results feed and rewrites it into the raw race shape the rest of the code consumes. |
| `static/index.html` | The dashboard: board, wave strip, KPI notes, wire panel, and provenance panel. |
| `export_static.py` | Builds the published snapshot: pulls the upstream, then writes the page and both payloads to `dist/`. |
| `.github/workflows/deploy.yml` | Runs the tests and the exporter, then deploys `dist/` to GitHub Pages. |
| `fixtures/` | Recorded payloads: civicAPI warm-up copies plus trimmed AP metadata and progress samples for the adapter tests. |
| `test_aggregate.py` | Unit tests for normalization, tallies, control projection, conflicts, and RSS parsing. |
| `test_ap_source.py` | Adapter tests: office mapping, seat naming, party expansion, progress joins, and call detection. |

## Local usage

```bash
cd ~/projects/us-midterms-tracker
python3 run.py
```

Open `http://localhost:8080`. The page re-reads the payload every 30 seconds and headlines every 60 seconds. The server polls the upstream on a 30 second cadence minus the round trip, and fetches its endpoints in parallel, so a slow upstream adds one call's latency instead of four. It keeps serving the last good payload if a poll fails, with the feed age and the error shown in the header.

**Refresh** forces an upstream poll rather than re-reading the server's cache: the page calls `/api/refresh`, then waits for a payload whose `refreshed_epoch` postdates the click before re-rendering. If a poll is already running, the request joins it instead of stacking a second round trip. A static Pages build has no endpoint, so the button only reloads the published snapshot there.

Run the tests with:

```bash
python3 -m unittest test_aggregate test_ap_source -v
```

## Deployment

GitHub Pages serves files and runs no Python, so the published site is a build-time snapshot. The workflow in `.github/workflows/deploy.yml` runs on every push to `main`, on manual dispatch, and every 15 minutes on a schedule. Each run tests the adapter, builds the snapshot, and deploys it.

The exporter calls the same code the local server uses, so the snapshot is the real payload rather than a canned file:

```bash
python3 export_static.py --out dist
```

It refuses to publish when the upstream is unreachable or when a payload comes back empty. The step fails and the previous deployment stays live, because a stale snapshot is better than a blank one.

One page serves both cases. It resolves `/api/races` and `/api/news` first and falls back to `data/races.json` and `data/news.json`, so the local server answers the API routes with live polling while Pages serves the snapshots. Snapshot payloads carry a `snapshot_epoch`, so the header reads "Static snapshot" with the build's age and the coverage stamp reads "as of" instead of "now". To rebuild the published snapshot on demand, run the workflow from the Actions tab.

GitHub disables scheduled workflows after 60 days without repository activity. Re-enable the schedule from the Actions tab if that happens.

## Known limits

The board covers 35 Senate contests, 435 House seats, 39 governor rows (36 states plus Guam, the Northern Mariana Islands, and the U.S. Virgin Islands), and the ballot measures the feed lists. Territories are tracked but excluded from the 50-state, 100-seat, and 435-seat arithmetic.

Results appear only after polls close, so before the first closing hour the board is empty by design; the "Hide races with no votes yet" control toggles that filter. The feed rounds its reporting percentage to a whole number on the search endpoint, so a race reading 100% may be a fraction short on the feed's own detail page.

Closing hours for Iowa, Nebraska, and Tennessee are flagged as disputed, and no 2026 official source confirms a closing hour for American Samoa, Guam, the Northern Mariana Islands, Puerto Rico, or the U.S. Virgin Islands. Both sets are labeled in the interface rather than presented as settled.
