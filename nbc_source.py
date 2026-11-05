"""Read NBC News election results and race calls from Firecracker API v2.

NBC News publishes election results and race calls from the NBC News Decision Desk
via its Firecracker API under:
https://www.nbcnews.com/firecracker/api/v2/national-results/2026-elections/races

The adapter parses NBC's race models and calls, translating them into the tracker's
canonical race format so that NBC race calls and vote tallies can be aggregated
alongside AP with full cross-source conflict detection.
"""

import json
import logging
import re
import urllib.error
import urllib.request

import aggregate

LOGGER = logging.getLogger("usmidterms.nbc")

NBC_RACES_URL = (
    "https://www.nbcnews.com/firecracker/api/v2/national-results/2026-elections/races"
)
NBC_REFERER = "https://www.nbcnews.com/politics/2026-elections"
USER_AGENT = "USMidtermTracker/1.0 (local election-night aggregator)"

TYPE_BY_OFFICE = {
    "house": aggregate.HOUSE_TYPE,
    "senate": aggregate.SENATE_TYPE,
    "governor": aggregate.GOVERNOR_TYPE,
    "measure": "Ballot Measure",
}

PARTY_MAP = {
    "DEM": "Democratic",
    "GOP": "Republican",
    "REP": "Republican",
    "LIB": "Libertarian",
    "GRN": "Green",
    "IND": "Independent",
}


def party_name(raw_code):
    """Normalize NBC party strings."""
    if not raw_code:
        return "Independent"
    code = str(raw_code).strip().upper()
    return PARTY_MAP.get(code, code.capitalize())


def _district(office_type, state, district_num):
    if office_type != "house":
        return None
    try:
        d = int(district_num)
        return f"{state}-{d:02d}"
    except (ValueError, TypeError):
        return None


def build_raw_races(payload):
    """Convert NBC's races document into the tracker's canonical raw race shape."""
    raw_list = payload.get("races") if isinstance(payload, dict) else payload
    if not isinstance(raw_list, list):
        return []

    races = []
    for item in raw_list:
        office = (item.get("office") or item.get("officeType") or "").lower()
        rtype = TYPE_BY_OFFICE.get(office)
        if rtype is None:
            continue

        state = item.get("state") or item.get("statePostal") or ""
        if not state or state == aggregate.NATIONAL_PROVINCE:
            continue

        race_id = str(item.get("id") or item.get("raceId") or f"nbc-{state}-{office}")
        cands_raw = item.get("candidates") or []
        candidates = []
        for c in cands_raw:
            name = c.get("name") or f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
            candidates.append({
                "name": name,
                "party": party_name(c.get("party")),
                "votes": int(c.get("voteCount") or c.get("votes") or 0),
                "percent": float(c.get("votePct") or c.get("percent") or 0.0),
                "winner": bool(c.get("winner") or c.get("isWinner") or c.get("projectedWinner")),
                "incumbent": bool(c.get("incumbent")),
            })

        call_status = item.get("callStatus") or item.get("status")
        if not call_status and any(c["winner"] for c in candidates):
            call_status = "Called"

        d_num = item.get("district") or item.get("districtNumber")
        dist = _district(office, state, d_num)

        election_name = item.get("name") or (
            f"{state} US House {int(d_num)}" if dist else f"{state} {rtype}"
        )

        races.append({
            "id": race_id,
            "type": rtype,
            "province": state,
            "district": dist,
            "election_name": election_name,
            "percent_reporting": float(item.get("reporting") or item.get("eevp") or 0.0),
            "candidates": candidates,
            "call_status": call_status,
            "tabulation": item.get("tabulation"),
            "poll_close_utc": item.get("pollCloseUtc"),
            "source": "NBC",
        })
    return races


def source_meta(payload):
    raw_list = payload.get("races") if isinstance(payload, dict) else payload
    count = len(raw_list) if isinstance(raw_list, list) else 0
    return {
        "provider": "NBC News",
        "url": NBC_RACES_URL,
        "races_on_feed": count,
        "last_updated": payload.get("lastUpdated") if isinstance(payload, dict) else None,
    }


def fetch_nbc_races(url=NBC_RACES_URL, timeout=8, attempts=2):
    """Fetch live NBC race calls document."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": NBC_REFERER,
            "Accept": "application/json",
        },
    )
    last_err = None
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return build_raw_races(data), source_meta(data)
        except Exception as exc:
            last_err = exc
    raise RuntimeError(f"NBC races request failed: {last_err}")
