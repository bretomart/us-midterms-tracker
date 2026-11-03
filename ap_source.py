"""Read AP's own election results feed.

AP News publishes the numbers behind
https://apnews.com/projects/elections-2026/us-house-results/ as plain JSON on
``interactives.apelections.org``. The CDN answers any request that carries an
AP News referer, so this needs no key, no token, and no HTML scraping. Two
documents hold everything on the page:

``data-live/<date>/results/national/metadata.json``
    One record per race, keyed by AP race id (``20261103KY20879``). Office,
    state, seat name, candidate roster with party and incumbency, first poll
    closing time, ``raceCallStatus`` ("Too Early to Call", "Called", ...) and
    ``tabulationStatus``.

``data-live/<date>/results/national/progress.json``
    Live counts: ``voteCount`` and ``votePct`` per candidate, the winner flag
    (``"winner": "X"``) AP sets at the moment it calls a race, percent of the
    expected vote counted (``eevp``), and ``lastUpdated``.

The adapter rewrites both into the raw race shape ``aggregate.normalise_race``
already consumes, so the board, tallies, closing schedule and tests keep
working unchanged. Nothing here guesses: a race only counts as called when AP
has flagged a winner.
"""

import concurrent.futures
import gzip
import json
import socket
import time
import urllib.error
import urllib.request
import zlib

import aggregate

EVENT_DATE = "2026-11-03"
BASE_URL = "https://interactives.apelections.org/election-results/data-live"
REFERER = "https://apnews.com/projects/elections-2026/us-house-results/"

USER_AGENT = "USMidtermTracker/1.0 (local election-night aggregator)"

# AP office codes -> the four sections the board knows. State legislature,
# mayor, retention and delegate races are on AP's feed but not on this board,
# so they are dropped instead of misfiled.
TYPE_BY_OFFICE = {
    "H": aggregate.HOUSE_TYPE,
    "S": aggregate.SENATE_TYPE,
    "G": aggregate.GOVERNOR_TYPE,
    "I": "Ballot Measure",
}

# AP's short party codes, expanded with the labels AP itself uses, except for
# the two majors: those keep the full names aggregate.party_group keys on.
# Codes missing here are rare third parties; they fall through unchanged.
PARTY_NAMES = {
    "DEM": "Democratic",
    "GOP": "Republican",
    "LIB": "Libertarian",
    "GRN": "Green",
    "IND": "Independent",
    "NP": "Non Partisan",
    "NPA": "No party affiliation",
    "UNA": "Unaffiliated",
    "UNR": "Unaffiliated",
    "IAP": "Independent American",
    "CST": "Constitution",
    "OTH": "Other",
    "YES": "Yes",
    "NO": "No",
}


def party_name(party):
    if not party:
        return None
    return PARTY_NAMES.get(party.strip().upper(), party)


def _get_json(url, timeout, attempts):
    """Fetch one AP document, retrying timeouts and 5xx responses."""
    last = None
    for attempt in range(attempts):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json, */*",
                "Referer": REFERER,
                "Origin": "https://apnews.com",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                encoding = (resp.headers.get("Content-Encoding") or "").lower()
            # The CDN compresses whether or not it was asked to.
            if encoding == "gzip" or body[:2] == b"\x1f\x8b":
                body = gzip.decompress(body)
            elif encoding == "deflate":
                body = zlib.decompress(body)
            return json.loads(body.decode("utf-8"))
        except (TimeoutError, socket.timeout, urllib.error.URLError,
                urllib.error.HTTPError, json.JSONDecodeError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(1.0 * (attempt + 1))
    raise last


def document_urls(event_date=EVENT_DATE):
    root = f"{BASE_URL}/{event_date}/results/national"
    return {
        "metadata": f"{root}/metadata.json",
        "progress": f"{root}/progress.json",
    }


def fetch_documents(event_date=EVENT_DATE, timeout=15, attempts=3):
    urls = document_urls(event_date)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(urls)) as pool:
        futures = {
            name: pool.submit(_get_json, url, timeout, attempts)
            for name, url in urls.items()
        }
        return {name: fut.result() for name, fut in futures.items()}


def _candidate_name(candidate):
    parts = [candidate.get("first"), candidate.get("last")]
    name = " ".join(p for p in parts if p)
    return name or candidate.get("last") or "Unknown"


def _district(office, meta):
    seat = meta.get("seatName") or ""
    if office == "H":
        digits = "".join(ch for ch in seat if ch.isdigit())
        if digits:
            return f"{meta.get('statePostal')}-{int(digits):02d}"
        return seat or None
    if office == "S":
        return seat or None
    if office == "I":
        return meta.get("designation") or None
    return None


def _race_name(rtype, state_name, meta):
    seat = meta.get("seatName") or ""
    if rtype == aggregate.HOUSE_TYPE:
        digits = "".join(ch for ch in seat if ch.isdigit())
        return f"{state_name} US House {int(digits)}" if digits else f"{state_name} US House"
    if rtype == aggregate.SENATE_TYPE:
        return f"{state_name} US Senate {seat}".strip() if seat and seat.lower() != "class" else f"{state_name} US Senate"
    if rtype == "Ballot Measure":
        label = seat.replace(" - ", ": ", 1)
        return f"{state_name} {label}".strip()
    return f"{state_name} {rtype}"


def build_raw_races(metadata, progress):
    """Convert AP's two documents into the tracker's raw race shape."""
    races = []
    for race_id, meta in metadata.items():
        office = meta.get("officeID")
        rtype = TYPE_BY_OFFICE.get(office)
        if rtype is None:
            continue
        state = meta.get("statePostal")
        # AP also ships a national popular-vote rollup (statePostal "US"); it is
        # an aggregate of the state rows, not a contest, so it stays out.
        if not state or state == aggregate.NATIONAL_PROVINCE:
            continue
        live = progress.get(race_id) or {}
        votes_by_id = {c.get("candidateID"): c for c in (live.get("candidates") or [])}
        roster = sorted(
            (meta.get("candidates") or {}).values(),
            key=lambda c: c.get("ballotOrder") or 0,
        )
        candidates = []
        for cand in roster:
            count = votes_by_id.get(cand.get("candidateID")) or {}
            candidates.append({
                "name": _candidate_name(cand),
                "party": party_name(cand.get("party")),
                "votes": int(count.get("voteCount") or 0),
                "percent": count.get("votePct") or 0,
                # AP sets this only once the race is called and the candidate
                # is the winner; a runoff or an early leader leaves it unset.
                "winner": count.get("winner") == "X",
                "incumbent": bool(cand.get("incumbent")),
            })
        races.append({
            "id": race_id,
            "type": rtype,
            "province": state,
            "district": _district(office, meta),
            "election_name": _race_name(rtype, live.get("stateName") or state, meta),
            # AP calls this the percent of the expected vote counted.
            "percent_reporting": live.get("eevp") or 0,
            "candidates": candidates,
            "call_status": meta.get("raceCallStatus"),
            "tabulation": meta.get("tabulationStatus"),
            "poll_close_utc": meta.get("firstPollClosingTime"),
        })
    return races


def source_meta(metadata, progress, event_date=EVENT_DATE):
    """Bookkeeping the page shows so the feed's own health is visible."""
    call_status = {}
    for meta in metadata.values():
        status = meta.get("raceCallStatus") or "unknown"
        call_status[status] = call_status.get(status, 0) + 1
    stamps = [p.get("lastUpdated") for p in progress.values() if p.get("lastUpdated")]
    return {
        "provider": "AP",
        "event_date": event_date,
        "documents": document_urls(event_date),
        "races_on_feed": len(metadata),
        "call_status": call_status,
        "last_updated": max(stamps) if stamps else None,
    }


def fetch_cycle(event_date=EVENT_DATE, timeout=15, attempts=3):
    """Pull AP's metadata and progress once and return raw races plus meta."""
    docs = fetch_documents(event_date=event_date, timeout=timeout, attempts=attempts)
    metadata, progress = docs["metadata"], docs["progress"]
    if not isinstance(metadata, dict) or not isinstance(progress, dict):
        raise ValueError("AP payloads were not objects")
    if not metadata:
        raise ValueError("AP metadata document was empty")
    races = build_raw_races(metadata, progress)
    if not races:
        raise ValueError("AP metadata held no races for the tracked offices")
    return races, source_meta(metadata, progress, event_date=event_date)
