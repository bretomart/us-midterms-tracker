# US Midterms Tracker

A single-screen dashboard for the November 3, 2026 US midterm elections. It pulls live vote tallies, race calls, the poll-closing schedule, national exit-poll crosstabs, and wire coverage into one page, published on GitHub Pages and also runnable locally against the upstream feeds directly.

Accuracy drives the design. Every number carries its source and its age, and sources that disagree are shown side by side instead of being averaged.

## What it shows

- **Race board:** every Senate, House, governor, and ballot-measure row the feed carries, with reporting percentage, standing, candidate votes, the closing hour for that jurisdiction, and any call the feed has published.
- **Last call per section:** under each summary panel (Senate, House, Governors, Measures), a card naming the race called most recently, its winner, and how long ago it was called. Clicking a card filters the board to that section.
- **Closing waves:** one card per distinct closing minute, split into the point where a jurisdiction's first precincts report and the point where it is fully closed.
- **Control arithmetic:** seats held before the election, seats not up this cycle, and how many seats each party needs for a majority in each chamber.
- **National exit polls:** the NBC News national exit poll, in the thirteen voter-group cuts the feed carries (all voters, race, gender, education, age, when the person voted), with each answer's share of the group and its Democrat/Republican vote split for the U.S. House. Questions are searchable.
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

Exit polls come from **NBC News**, which publishes the National Election Pool's national poll as a structured document behind its exit-poll page. `https://www.nbcnews.com/politics/2026-elections/exit-polls` is drawn by the same Firecracker API as its results pages, and `national-results/2026-elections/exit-polls` holds every voter group in one response: the composition share of each answer, the Democrat and Republican vote split for the U.S. House within that group, the poll's phase, the methodology text, and the pollster credit. The adapter in `exitpoll.py` keeps all of it and invents nothing: a percentage the feed does not carry stays null, and the feed's `-1` for "nobody in this group answered" becomes null rather than a negative number.

The poll is self-reported and asks one thing, how the respondent voted for the U.S. House. Its percentages are never added to the tallies, never averaged with them, and never used to call a race. Only the national cuts are read: NBC carries state and district crosstabs on individual pages with no stable per-race feed, so none is scraped, and the wire covers those figures as outlets publish them.

Sources that were rejected, with the observed failure: the AP Elections REST API (key-gated, paid; the interactive feed is the public surface of the same numbers), Decision Desk HQ (`votes.decisiondeskHQ.com` returned HTTP 429, API paid), and AP VoteCast (no reachable host: DNS failures and HTTP 403).

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
| `exitpoll.py` | Reads NBC's national exit poll document and flattens it into voter groups, questions, and answer rows. |
| `call_log.py` | Stamps the first poll that saw each race called, orders those stamps per section, and persists them in `state/call_log.json`. |
| `static/index.html` | The dashboard: board, wave strip, KPI notes, exit poll panel, wire panel, and provenance panel. |
| `export_static.py` | Builds the published snapshot: pulls every upstream, then writes the page and its three payloads to `dist/`. |
| `publish.py` | Dispatches the Pages workflow from the local server on a timer, for when GitHub's cron drops or delays scheduled runs. |
| `.github/workflows/deploy.yml` | Runs the tests and the exporter, then deploys `dist/` to GitHub Pages. |
| `fixtures/` | Recorded payloads: civicAPI warm-up copies, trimmed AP metadata and progress samples, and the exit poll document for the adapter tests. |
| `test_aggregate.py` | Unit tests for normalization, tallies, control projection, conflicts, and RSS parsing. |
| `test_ap_source.py` | Adapter tests: office mapping, seat naming, party expansion, progress joins, and call detection. |
| `test_exitpoll.py` | Adapter tests for the exit poll: group order, question numbering, party pairing, missing values, and credit cleanup. |
| `test_call_log.py` | Tests for call ordering: settling window, unstamped fallback, latest stamp wins, restart persistence, uncalled races. |
| `test_publish.py` | Tests for the dispatch timer: interval gating, failure backoff, and `PUBLISH_INTERVAL` parsing. |

## Local usage

```bash
cd ~/projects/us-midterms-tracker
python3 run.py
```

Open `http://localhost:8080`. The page re-reads the payload every 30 seconds, headlines every 60 seconds, and the exit poll every five minutes. The server polls the upstream on a 30 second cadence minus the round trip, and fetches its endpoints in parallel, so a slow upstream adds one call's latency instead of four. It keeps serving the last good payload if a poll fails, with the feed age and the error shown in the header.

**Refresh** forces an upstream poll rather than re-reading the server's cache: the page calls `/api/refresh`, then waits for a payload whose `refreshed_epoch` postdates the click before re-rendering. If a poll is already running, the request joins it instead of stacking a second round trip. A static Pages build has no endpoint to call, so there the button watches the deployed files instead: it keeps asking for `data/races.json` until a build with a newer `snapshot_epoch` lands (up to two minutes), swapping the board in when it does.

The published page also accepts a live source. Once the site is on Pages, `?live=http://host:8080` points the page at a server that is actually polling, and the choice persists in `localStorage`, so the 30 second poll resumes and the page stops being a snapshot. `?live=` with no value clears it. An unreachable server falls back to the shipped files on the next fetch; the page can be cross-origin, so this works against a tunnel as well as a host on the local network.

Run the tests with:

```bash
python3 -m unittest discover -v
```

## Deployment

GitHub Pages serves files and runs no Python, so the published site is a build-time snapshot. The workflow in `.github/workflows/deploy.yml` runs on every push to `main`, on manual dispatch, and every 5 minutes on a schedule. Each run tests every module, builds the snapshot, and deploys it.

The schedule is the weak link: GitHub's cron is best-effort and drops or delays scheduled runs under load, so the published age is whatever the last run produced, and the header reports it rather than pretending otherwise. Pages also caches files for ten minutes, so the page fetches its payloads with a buster and `cache: 'no-store'`; a fresh deployment shows on the next 30 second poll, with no hard reload.

When the schedule cannot be trusted, the local server can dispatch the workflow itself:

```bash
PUBLISH_INTERVAL=300 python3 run.py
```

With that set, the server asks GitHub for a rebuild every five minutes while it runs, using the authenticated `gh` CLI, and backs off for ten minutes after a failed dispatch instead of retrying on every tick. The workflow still builds and deploys; the server only starts it. Unset, `PUBLISH_INTERVAL` does nothing, so starting the tracker never publishes as a side effect.

The exporter calls the same code the local server uses, so the snapshot is the real payload rather than a canned file:

```bash
python3 export_static.py --out dist
```

It refuses to publish when the upstream is unreachable or when a payload comes back empty. The step fails and the previous deployment stays live, because a stale snapshot is better than a blank one.

One page serves both cases. `export_static.py` writes `data-mode="snapshot"` onto the `<html>` element it publishes, and the page reads that mark to fetch `data/races.json`, `data/news.json`, and `data/exitpolls.json` directly. The local server serves the unmarked file, which fetches `/api/races`, `/api/news`, and `/api/exitpolls` first and falls back to the data files. Marking the build is what keeps the published page from asking a static host for endpoints it cannot answer: unmarked, every visit collected three 404s before the fallback ran. Snapshot payloads carry a `snapshot_epoch`, so the header reads "Static snapshot" with the build's age and the coverage stamp reads "as of" instead of "now". To rebuild the published snapshot on demand, run the workflow from the Actions tab.

The race and headline payloads gate the deploy: a run that cannot reach either one fails and leaves the previous deployment live. The exit poll is supplementary, so a failed pull prints a line and ships the page without it, and the panel then states that the feed is unreachable instead of showing a stale poll as current.

GitHub disables scheduled workflows after 60 days without repository activity. Re-enable the schedule from the Actions tab if that happens.

## Known limits

The board covers 35 Senate contests, 435 House seats, 39 governor rows (36 states plus Guam, the Northern Mariana Islands, and the U.S. Virgin Islands), and the ballot measures the feed lists. Territories are tracked but excluded from the 50-state, 100-seat, and 435-seat arithmetic.

Results appear only after polls close, so before the first closing hour the board is empty by design; the "Hide races with no votes yet" control toggles that filter. The feed rounds its reporting percentage to a whole number on the search endpoint, so a race reading 100% may be a fraction short on the feed's own detail page.

AP publishes no timestamp for its race calls: metadata carries `raceCallStatus` and the winner flag, and progress `lastUpdated` moves on every count update, not on the call. The last-call cards therefore order calls by when this tracker first saw them, stamped on each poll and kept in `state/call_log.json`. Calls already published when the tracker starts, or within its first three minutes, cannot be ordered against each other; those cards read "already called at HH:MM UTC" and fall back to the furthest-along race in the section instead of claiming a false age.

Closing hours for Iowa, Nebraska, and Tennessee are flagged as disputed, and no 2026 official source confirms a closing hour for American Samoa, Guam, the Northern Mariana Islands, Puerto Rico, or the U.S. Virgin Islands. Both sets are labeled in the interface rather than presented as settled.

The exit poll panel covers the national poll only. The feed repeats question titles (two "Age" cuts), so the panel numbers the repeats instead of rewriting them, and questions whose respondents all answered the same way show `--` for the groups the feed marks inapplicable. The poll is a snapshot of who turned out and how they say they voted, not a running count; NBC revisits and reweights it through the night, and the panel prints the feed's own update stamp each time it refetches.
