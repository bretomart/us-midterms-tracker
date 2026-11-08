import concurrent.futures
import email.utils
import html
import http.server
import json
import os
import re
import socket
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

import aggregate
import ap_source
import baseline
import call_log
import exitpoll
import publish
import schedule

PORT = int(os.environ.get("PORT", "8080"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIRECTORY = os.path.join(BASE_DIR, "static")
FIXTURES_DIR = os.path.join(BASE_DIR, "fixtures")

SOURCE_AP = "AP (interactives.apelections.org)"
SOURCE_CIVICAPI = "civicAPI v2 (https://civicapi.org)"
SOURCE_FIXTURES = "Recorded fixtures (fixtures/)"

POLL_INTERVAL = 30
NEWS_POLL_INTERVAL = 60
# The exit poll feed republishes on its own schedule, and NBC stamps the poll
# with its own update hour, so a slower poll loses nothing but stale bytes.
EXIT_POLL_INTERVAL = 300

RSS_PROVIDERS = [
    {
        "id": "msnow",
        "name": "MS NOW",
        "url": "https://www.ms.now/feed",
        "color": "#38bdf8",
    },
    {
        "id": "cnn",
        "name": "CNN Politics",
        "url": "http://rss.cnn.com/rss/cnn_allpolitics.rss",
        "color": "#ef4444",
    },
    {
        "id": "fox",
        "name": "Fox News Politics",
        "url": "https://moxie.foxnews.com/google-publisher/politics.xml",
        "color": "#f59e0b",
    },
    {
        "id": "nbc",
        "name": "NBC News Politics",
        "url": "https://feeds.nbcnews.com/nbcnews/public/politics",
        "color": "#818cf8",
    },
    {
        "id": "npr",
        "name": "NPR Politics",
        "url": "https://feeds.npr.org/1014/rss.xml",
        "color": "#34d399",
    },
    {
        "id": "pbs",
        "name": "PBS NewsHour",
        "url": "https://www.pbs.org/newshour/feeds/rss/politics",
        "color": "#a78bfa",
    },
    {
        "id": "cbs",
        "name": "CBS News Politics",
        "url": "https://www.cbsnews.com/latest/rss/politics",
        "color": "#60a5fa",
    },
    {
        "id": "abc",
        "name": "ABC News Politics",
        "url": "https://abcnews.go.com/abcnews/politicsheadlines",
        "color": "#fb7185",
    },
    {
        "id": "politico",
        "name": "Politico",
        "url": "https://rss.politico.com/politics-news.xml",
        "color": "#f43f5e",
    },
    {
        "id": "thehill",
        "name": "The Hill",
        "url": "https://thehill.com/homenews/feed/",
        "color": "#2dd4bf",
    },
]

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

_STATE_LOCK = threading.Lock()
_STATE = {
    "payload": None,
    "last_refresh_epoch": 0.0,
    "source_status": "INITIALIZING",
    "upstream_error": None,
    "refreshing": False,
}

# Held for the whole upstream round trip, so the scheduled poller and a manual
# refresh can never hammer the upstream feeds at the same time.
_REFRESH_LOCK = threading.Lock()

_NEWS_LOCK = threading.Lock()
_NEWS_STATE = {
    "items": [],
    "providers": {},
    "fetched_at": None,
    "last_refresh_epoch": 0.0,
}
_EXIT_LOCK = threading.Lock()
_EXIT_STATE = {
    "payload": None,
    "fetched_at": None,
    "last_refresh_epoch": 0.0,
    "error": None,
}


def _clean_html_text(raw_text, max_len=240):
    if not raw_text:
        return ""
    stripped = _TAG_RE.sub(" ", raw_text)
    unescaped = html.unescape(stripped)
    unescaped = unescaped.replace("\u2014", " - ").replace("\u2013", "-")
    collapsed = _WS_RE.sub(" ", unescaped).strip()
    if len(collapsed) > max_len:
        return collapsed[: max_len - 3].rstrip() + "..."
    return collapsed


def _parse_pubdate(raw_date):
    if not raw_date:
        return 0.0, ""
    raw_date = raw_date.strip()
    try:
        dt = email.utils.parsedate_to_datetime(raw_date)
        ts = dt.timestamp()
        return ts, time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts))
    except Exception:
        pass
    # Fallback for ISO-8601 strings
    try:
        clean_iso = raw_date.replace("Z", "+00:00")
        from datetime import datetime
        dt = datetime.fromisoformat(clean_iso)
        ts = dt.timestamp()
        return ts, time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts))
    except Exception:
        return 0.0, raw_date


def parse_rss_xml(xml_bytes, provider_meta, limit=12):
    """Parse RSS 2.0 or Atom XML bytes into normalised news items."""
    root = ET.fromstring(xml_bytes)
    items = []

    # RSS 2.0 <item> elements
    rss_items = root.findall(".//item")
    if rss_items:
        for node in rss_items[:limit]:
            title = _clean_html_text(node.findtext("title") or "", max_len=200)
            link = (node.findtext("link") or "").strip()
            desc = _clean_html_text(node.findtext("description") or "", max_len=240)
            pub_raw = (
                node.findtext("pubDate")
                or node.findtext("{http://purl.org/dc/elements/1.1/}date")
                or ""
            )
            ts, pub_fmt = _parse_pubdate(pub_raw)
            if not title or not link:
                continue
            items.append({
                "provider_id": provider_meta["id"],
                "provider_name": provider_meta["name"],
                "provider_color": provider_meta.get("color", "#6366f1"),
                "title": title,
                "link": link,
                "summary": desc,
                "published_at": pub_fmt,
                "timestamp": ts,
            })
        return items

    # Atom <entry> elements
    atom_entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    for node in atom_entries[:limit]:
        title = _clean_html_text(
            node.findtext("{http://www.w3.org/2005/Atom}title") or "", max_len=200
        )
        link_el = node.find("{http://www.w3.org/2005/Atom}link")
        link = (link_el.get("href") if link_el is not None else "") or ""
        desc = _clean_html_text(
            node.findtext("{http://www.w3.org/2005/Atom}summary")
            or node.findtext("{http://www.w3.org/2005/Atom}content")
            or "",
            max_len=240,
        )
        pub_raw = (
            node.findtext("{http://www.w3.org/2005/Atom}updated")
            or node.findtext("{http://www.w3.org/2005/Atom}published")
            or ""
        )
        ts, pub_fmt = _parse_pubdate(pub_raw)
        if not title or not link:
            continue
        items.append({
            "provider_id": provider_meta["id"],
            "provider_name": provider_meta["name"],
            "provider_color": provider_meta.get("color", "#6366f1"),
            "title": title,
            "link": link.strip(),
            "summary": desc,
            "published_at": pub_fmt,
            "timestamp": ts,
        })
    return items


def _fetch_one_rss(provider, timeout=7):
    req = urllib.request.Request(
        provider["url"],
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; USMidtermTracker/1.0)",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw_bytes = resp.read()
    return parse_rss_xml(raw_bytes, provider, limit=12)


def refresh_news_feeds():
    all_items = []
    provider_status = {}
    threads = []
    results_lock = threading.Lock()

    def _worker(prov):
        t0 = time.time()
        try:
            parsed = _fetch_one_rss(prov, timeout=7)
            elapsed = round(time.time() - t0, 2)
            with results_lock:
                all_items.extend(parsed)
                provider_status[prov["id"]] = {
                    "id": prov["id"],
                    "name": prov["name"],
                    "color": prov["color"],
                    "url": prov["url"],
                    "status": "OK",
                    "count": len(parsed),
                    "latency_s": elapsed,
                    "error": None,
                }
        except Exception as exc:
            with results_lock:
                provider_status[prov["id"]] = {
                    "id": prov["id"],
                    "name": prov["name"],
                    "color": prov["color"],
                    "url": prov["url"],
                    "status": "ERROR",
                    "count": 0,
                    "latency_s": round(time.time() - t0, 2),
                    "error": str(exc),
                }

    for prov in RSS_PROVIDERS:
        t = threading.Thread(target=_worker, args=(prov,), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=9)

    # Sort newest first; items without a timestamp go after timestamped items
    all_items.sort(key=lambda x: x.get("timestamp") or 0.0, reverse=True)
    fetched_at = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

    with _NEWS_LOCK:
        if all_items or not _NEWS_STATE["items"]:
            _NEWS_STATE["items"] = all_items
        _NEWS_STATE["providers"] = [
            provider_status.get(
                p["id"],
                {
                    "id": p["id"],
                    "name": p["name"],
                    "color": p["color"],
                    "url": p["url"],
                    "status": "TIMEOUT",
                    "count": 0,
                    "error": "Timed out",
                },
            )
            for p in RSS_PROVIDERS
        ]
        _NEWS_STATE["fetched_at"] = fetched_at
        _NEWS_STATE["last_refresh_epoch"] = time.time()


def _news_poller_loop():
    while True:
        refresh_news_feeds()
        time.sleep(NEWS_POLL_INTERVAL)


def load_exit_polls_from_fixture():
    """Warm the exit poll panel from the recorded feed.

    A cold start has nothing to show until the first upstream pull returns,
    and a transient failure must not blank a panel that already had data.
    """
    data = _load_fixture_json("exitpolls_2026-11-03.json")
    if not data:
        return None
    with _EXIT_LOCK:
        _EXIT_STATE["payload"] = data
        _EXIT_STATE["fetched_at"] = data.get("fetched_at")
        if not _EXIT_STATE["last_refresh_epoch"]:
            _EXIT_STATE["last_refresh_epoch"] = time.time()
    return data


def refresh_exit_polls():
    """Pull the national exit poll. Returns True when the payload moved."""
    try:
        payload = exitpoll.refresh(timeout=15, attempts=2)
    except Exception as exc:
        with _EXIT_LOCK:
            _EXIT_STATE["error"] = f"{type(exc).__name__}: {exc}"
        return False

    with _EXIT_LOCK:
        current = _EXIT_STATE["payload"] or {}
        error = _EXIT_STATE["error"]
        # An empty document is a failed pull, not a poll with zero questions.
        # Keep the last good payload rather than trading data for a blank panel.
        if not payload.get("subsets") and current.get("subsets"):
            _EXIT_STATE["error"] = error or "feed returned no voter groups"
            return False
        _EXIT_STATE["payload"] = payload
        _EXIT_STATE["fetched_at"] = payload.get("fetched_at")
        _EXIT_STATE["last_refresh_epoch"] = time.time()
        _EXIT_STATE["error"] = None
    return True


def _exit_poller_loop():
    while True:
        refresh_exit_polls()
        time.sleep(EXIT_POLL_INTERVAL)


def _load_fixture_json(filename):
    path = os.path.join(FIXTURES_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _fetch_url_json(url, timeout=8, attempts=3):
    """GET a JSON document, retrying timeouts.

    civicAPI latency swings from a fraction of a second to well past ten, so a
    single attempt at a tight timeout drops most election-night polls. The last
    error is re-raised so refresh_from_upstream can keep serving the previous
    payload and say so.
    """
    last = None
    for attempt in range(attempts):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "USMidtermTracker/1.0 (local election-night aggregator)",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise last


def _dedupe_races(raw_races):
    by_id = {}
    for r in raw_races:
        rid = r.get("id")
        if rid is not None:
            by_id[rid] = r
    return list(by_id.values())


def build_board_payload(raw_races, national_raw, source_status, fetched_at, upstream_error=None,
                        epoch=None, source_label=SOURCE_CIVICAPI, source_meta=None):
    deduped = _dedupe_races(raw_races)
    normalised = [aggregate.normalise_race(r) for r in deduped]
    if epoch is None:
        epoch = time.time()
    now_index = schedule.et_now_index(epoch)
    schedule.attach(normalised, now_index=now_index)
    board = aggregate.split_board(normalised)

    senate_tally = aggregate.tally(board["senate"])
    house_tally = aggregate.tally(board["house"])
    governor_tally = aggregate.tally(board["governor"])
    measures_tally = aggregate.tally(board["measures"])

    # Territories sit in the governor board but not in the 50-state majority
    # arithmetic, so the two counts are reported apart.
    gov_states = [r for r in board["governor"] if r["state"] in aggregate.STATE_CODES]
    gov_terr = [r for r in board["governor"] if r["state"] not in aggregate.STATE_CODES]
    gov_states_tally = aggregate.tally(gov_states)

    senate_feed = aggregate.feed_seats(national_raw.get("senate") or {})
    house_feed = aggregate.feed_seats(national_raw.get("house") or {})
    discrepancies = aggregate.conflicts(board, national_raw)
    call_times = call_log.observe(
        [r for name in call_log.SECTIONS for r in board[name]], epoch=epoch)

    senate_total = {g: baseline.SENATE["holdover"][g] + senate_tally["called"][g]
                    for g in ("D", "R", "O")}
    house_total = {g: house_tally["called"][g] for g in ("D", "R", "O")}

    return {
        "fetched_at": fetched_at,
        "source": source_label,
        "source_meta": source_meta,
        "source_status": source_status,
        "upstream_error": upstream_error,
        "summary": {
            "senate": {
                "majority": baseline.SENATE["majority"],
                "total_seats": baseline.SENATE["total_seats"],
                "contested": senate_tally["races"],
                "holdover": baseline.SENATE["holdover"],
                "held_before": baseline.SENATE["held_before"],
                "feed_seats": senate_feed,
                "total": senate_total,
                "control": aggregate.control(senate_total, baseline.SENATE["majority"],
                                             senate_tally["races"] - senate_tally["no_data"]),
                "tally": senate_tally,
            },
            "house": {
                "majority": baseline.HOUSE["majority"],
                "total_seats": baseline.HOUSE["total_seats"],
                "contested": house_tally["races"],
                "held_before": baseline.HOUSE["held_before"],
                "vacant": baseline.HOUSE["vacant"],
                "feed_seats": house_feed,
                "total": house_total,
                "control": aggregate.control(house_total, baseline.HOUSE["majority"],
                                             house_tally["races"] - house_tally["no_data"]),
                "tally": house_tally,
            },
            "governor": {
                "majority": baseline.GOVERNOR["majority"],
                "total_offices": baseline.GOVERNOR["total_offices"],
                "contested": governor_tally["races"],
                "contested_states": gov_states_tally["races"],
                "territories": len(gov_terr),
                "held_before": baseline.GOVERNOR["held_before"],
                "tally": gov_states_tally,
                "tally_all": governor_tally,
            },
            "measures": {
                "contested": measures_tally["races"],
                "tally": measures_tally,
            },
        },
        "baseline": baseline.block(),
        "schedule": schedule.schedule_block(now_index=now_index, epoch=epoch),
        "waves": schedule.waves(_jurisdiction_counts(board), now_index=now_index),
        "conflicts": discrepancies,
        "board": {
            "senate": board["senate"],
            "house": board["house"],
            "governor": board["governor"],
            "measures": board["measures"],
            "last_called": call_log.last_by_section(board, call_times),
        },
        "races": deduped,
    }


def _jurisdiction_counts(board):
    """Map province code to the number of races the feed carries for it."""
    counts = {}
    for section in ("senate", "house", "governor", "measures"):
        for race in board[section]:
            counts[race["state"]] = counts.get(race["state"], 0) + 1
    return counts


def load_from_fixtures(reason="FIXTURE-CACHE"):
    gen = _load_fixture_json("general_2026-11-03.json") or {}
    sw = _load_fixture_json("statewide_2026-11-03.json") or {}
    nat_house = _load_fixture_json("race_87524.json") or {}
    nat_senate = _load_fixture_json("race_87528.json") or {}

    raw_races = (gen.get("races") or []) + (sw.get("races") or [])
    national_raw = {"house": nat_house, "senate": nat_senate}
    fetched_at = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

    payload = build_board_payload(
        raw_races=raw_races,
        national_raw=national_raw,
        source_status=reason,
        fetched_at=fetched_at,
        source_label=SOURCE_FIXTURES,
    )
    with _STATE_LOCK:
        _STATE["payload"] = payload
        _STATE["last_refresh_epoch"] = time.time()
        _STATE["source_status"] = reason
    return payload


def _search_url(election_type):
    return (
        "https://civicapi.org/api/v2/race/search"
        f"?startDate=2026-11-03&endDate=2026-11-03&country=US&election_type={election_type}&limit=1000"
    )


def _fetch_sources():
    """Pull the four endpoints the board is built from, concurrently.

    Serially a healthy cycle cost about 20 seconds and a timing-out one cost
    nearly three minutes, which left the board ageing well past its poll
    interval and made the refresh button feel dead. The four calls are
    independent, so a cycle now costs its slowest call instead of their sum.
    """
    jobs = [
        (_search_url("General"), 15, 2),
        (_search_url("Statewide"), 15, 2),
        ("https://civicapi.org/api/v2/race/87524", 10, 1),
        ("https://civicapi.org/api/v2/race/87528", 10, 1),
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = [pool.submit(_fetch_url_json, url, timeout=t, attempts=a) for url, t, a in jobs]
        general, statewide, nat_house, nat_senate = (f.result() for f in futures)
    return (
        (general.get("races") or []) + (statewide.get("races") or []),
        {"house": nat_house, "senate": nat_senate},
    )


def _fetch_ap():
    """Read AP's own results feed. Raises when AP cannot be reached."""
    raw_races, meta = ap_source.fetch_cycle()
    # AP publishes no national seat table, so the seat cross-check is skipped
    # rather than fed zeros that would read as a disagreement.
    return raw_races, {}, "LIVE-AP", SOURCE_AP, meta


def _fetch_civicapi():
    raw_races, national_raw = _fetch_sources()
    return raw_races, national_raw, "LIVE-CIVICAPI", SOURCE_CIVICAPI, None


def _fetch_results():
    """Pull the board from AP, falling back to civicAPI when AP is down."""
    errors = []
    for name, fetch in (("AP", _fetch_ap), ("civicAPI", _fetch_civicapi)):
        try:
            return fetch()
        except Exception as exc:  # noqa: BLE001 - any failure moves to the fallback
            errors.append(f"{name}: {exc}")
    raise RuntimeError("; ".join(errors))


def _refresh_from_upstream_unlocked():
    try:
        raw_races, national_raw, status, label, meta = _fetch_results()

        fetched_at = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        payload = build_board_payload(
            raw_races=raw_races,
            national_raw=national_raw,
            source_status=status,
            fetched_at=fetched_at,
            upstream_error=None,
            source_label=label,
            source_meta=meta,
        )
        with _STATE_LOCK:
            _STATE["payload"] = payload
            _STATE["last_refresh_epoch"] = time.time()
            _STATE["source_status"] = status
            _STATE["upstream_error"] = None
        return True
    except Exception as exc:
        with _STATE_LOCK:
            _STATE["upstream_error"] = str(exc)
            if _STATE["payload"] is not None:
                _STATE["payload"]["upstream_error"] = str(exc)
                if str(_STATE["source_status"]).startswith("LIVE-"):
                    _STATE["source_status"] = "LIVE-CACHED (UPSTREAM ERROR)"
                    _STATE["payload"]["source_status"] = _STATE["source_status"]
        return False


def refresh_from_upstream(wait=True):
    """Poll civicAPI once.

    ``wait=False`` skips the cycle when another refresh already holds the lock,
    which is what the poller and the manual refresh endpoint want: a queued
    request would only stack a second full round trip behind the first.
    """
    if not wait:
        if not _REFRESH_LOCK.acquire(blocking=False):
            return False
        try:
            with _STATE_LOCK:
                _STATE["refreshing"] = True
            return _refresh_from_upstream_unlocked()
        finally:
            with _STATE_LOCK:
                _STATE["refreshing"] = False
            _REFRESH_LOCK.release()

    with _REFRESH_LOCK:
        with _STATE_LOCK:
            _STATE["refreshing"] = True
        try:
            return _refresh_from_upstream_unlocked()
        finally:
            with _STATE_LOCK:
                _STATE["refreshing"] = False


def start_refresh_async():
    """Kick a refresh on a worker thread. Returns True when one was started."""
    with _STATE_LOCK:
        if _STATE["refreshing"]:
            return False
        # Claim the flag here so a caller can report work in flight immediately.
        _STATE["refreshing"] = True
    threading.Thread(target=refresh_from_upstream, kwargs={"wait": False}, daemon=True).start()
    return True


def _poller_loop():
    while True:
        started = time.time()
        refresh_from_upstream(wait=False)
        # POLL_INTERVAL is the target gap between polls, not a fixed sleep, so a
        # slow round trip does not push the next one out by another 30s.
        elapsed = time.time() - started
        time.sleep(max(5.0, POLL_INTERVAL - elapsed))


class DualStackThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self):
        if getattr(socket, "has_ipv6", False) and self.address_family == socket.AF_INET6:
            try:
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            except Exception:
                pass
        super().server_bind()


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_GET(self):
        if self.path.startswith("/api/news"):
            self.handle_news_api()
        elif self.path.startswith("/api/exitpolls"):
            self.handle_exit_api()
        elif self.path.startswith("/api/refresh"):
            self.handle_refresh()
        elif self.path.startswith("/api/"):
            self.handle_api()
        else:
            super().do_GET()

    def do_HEAD(self):
        if self.path.startswith("/api/news"):
            self.handle_news_api()
        elif self.path.startswith("/api/exitpolls"):
            self.handle_exit_api()
        elif self.path.startswith("/api/refresh"):
            self.handle_refresh()
        elif self.path.startswith("/api/"):
            self.handle_api()
        else:
            super().do_HEAD()

    def _send_json(self, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command == "GET":
            self.wfile.write(body)

    def handle_news_api(self):
        with _NEWS_LOCK:
            age = (
                round(time.time() - _NEWS_STATE["last_refresh_epoch"], 1)
                if _NEWS_STATE["last_refresh_epoch"]
                else 0.0
            )
            out = {
                "fetched_at": _NEWS_STATE["fetched_at"],
                "cache_age_seconds": age,
                "providers": _NEWS_STATE["providers"],
                "items": _NEWS_STATE["items"],
            }
        self._send_json(out)

    def handle_exit_api(self):
        with _EXIT_LOCK:
            payload = _EXIT_STATE["payload"]
            age = (
                round(time.time() - _EXIT_STATE["last_refresh_epoch"], 1)
                if _EXIT_STATE["last_refresh_epoch"] else 0.0
            )
            error = _EXIT_STATE["error"]
        if payload is None:
            payload = load_exit_polls_from_fixture() or {}
        out = dict(payload)
        out["cache_age_seconds"] = age
        out["upstream_error"] = error
        self._send_json(out)

    def handle_refresh(self):
        started = start_refresh_async()
        threading.Thread(target=refresh_exit_polls, daemon=True).start()
        with _STATE_LOCK:
            payload = _STATE["payload"]
            age = round(time.time() - _STATE["last_refresh_epoch"], 1) if _STATE["last_refresh_epoch"] else 0.0
            out = {
                "accepted": started,
                "refreshing": _STATE["refreshing"],
                "cache_age_seconds": age,
                "refreshed_epoch": round(_STATE["last_refresh_epoch"], 3),
                "fetched_at": (payload or {}).get("fetched_at"),
            }
        self._send_json(out)

    def handle_api(self):
        with _STATE_LOCK:
            payload = _STATE["payload"]
            age = round(time.time() - _STATE["last_refresh_epoch"], 1) if _STATE["last_refresh_epoch"] else 0.0
            refreshing = _STATE["refreshing"]
            refreshed_epoch = round(_STATE["last_refresh_epoch"], 3)

        if payload is None:
            payload = load_from_fixtures("FIXTURE-FALLBACK")

        out = dict(payload)
        out["cache_age_seconds"] = age
        out["refreshing"] = refreshing
        out["refreshed_epoch"] = refreshed_epoch
        self._send_json(out)

    def log_message(self, format, *args):
        sys.stderr.write(f"[HTTP SERVER] {self.address_string()} - {format % args}\n")


def _create_server(port):
    if getattr(socket, "has_ipv6", False):
        try:
            class IPv6Server(DualStackThreadingHTTPServer):
                address_family = socket.AF_INET6
            return IPv6Server(("::", port), ProxyHandler)
        except Exception:
            pass
    return DualStackThreadingHTTPServer(("0.0.0.0", port), ProxyHandler)


def _publish_loop(publisher):
    while True:
        try:
            publisher.tick()
        except Exception as exc:  # noqa: BLE001 - a publisher must not take the server down
            print(f"[PUBLISH] unexpected error: {exc}", file=sys.stderr, flush=True)
        time.sleep(15)


def run_server():
    if call_log.seed_from_fixture():
        print("[CALL LOG] ledger had no call times; seeded them from fixtures/call_log.json")
    load_from_fixtures("FIXTURE-WARMUP")
    load_exit_polls_from_fixture()
    poller = threading.Thread(target=_poller_loop, daemon=True)
    poller.start()
    news_poller = threading.Thread(target=_news_poller_loop, daemon=True)
    news_poller.start()
    exit_poller = threading.Thread(target=_exit_poller_loop, daemon=True)
    exit_poller.start()
    # PUBLISH_INTERVAL turns on a dispatch of the Pages workflow on a timer.
    # Unset by default: publishing is a deliberate act, not a side effect of
    # starting the tracker.
    publisher = publish.from_env(cwd=BASE_DIR)
    if publisher:
        threading.Thread(target=_publish_loop, args=(publisher,), daemon=True).start()
        print(f"[PUBLISH] dispatching {publish.WORKFLOW} every {publisher.interval}s while this server runs")

    ports = [8080, 8081]
    servers = []
    for p in ports:
        try:
            srv = _create_server(p)
            servers.append(srv)
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            print(f"US Midterm Tracker serving on http://localhost:{p}")
        except OSError as exc:
            print(f"[WARN] Could not bind port {p}: {exc}", file=sys.stderr)
    sys.stdout.flush()
    if not servers:
        raise RuntimeError("Could not bind any HTTP port (8080, 8081)")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        for s in servers:
            s.shutdown()


if __name__ == "__main__":
    run_server()
