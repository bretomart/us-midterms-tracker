"""Order race calls that the feed itself does not timestamp.

AP's metadata carries ``raceCallStatus`` and a per-candidate winner flag but no
call time, and progress ``lastUpdated`` moves on every vote-count update, so
neither field can tell which race was called most recently. The tracker
stamps the first poll in which it saw a race called and keeps that stamp.

The opening window after the log is created cannot be ordered: every race
first seen in it was already called before tracking began, so those entries
stay 0 and the page reports the tracker's start time instead of inventing an
age. See ``SETTLE_SECONDS``.
"""

import json
import os
import threading
import time

import aggregate

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE_DIR, "state")
LOG_PATH = os.path.join(STATE_DIR, "call_log.json")
# Committed copy of the observed call times. A call stamp cannot be recovered
# from the feed, so a cold start (new clone, restored or missing cache) begins
# from this history instead of an empty ledger.
SEED_PATH = os.path.join(BASE_DIR, "fixtures", "call_log.json")

SECTIONS = ("senate", "house", "governor", "measures")

# Calls seen inside this window after the log is created cannot be ordered.
# The tracker starts against a fixture warm-up and switches to the live feed a
# poll later, so every race already called upstream would otherwise look like a
# fresh call. Three minutes covers the first live poll and costs only the
# stamps of genuine calls made in that opening window.
SETTLE_SECONDS = 180

_LOCK = threading.Lock()
_CACHE = None


def race_identity(row):
    """Stable identity for one board row across the two feeds, or None.

    AP and civicAPI give the same race different ids (20261103MS26692 vs
    81004), so a call stamp keyed by feed id cannot survive a source switch
    or be compared across feeds. The identity is the contest itself:

    - Senate and governor: the state. Each has one contest per state, and the
      feeds label the district differently (AP "Class II", civicAPI nothing;
      AP nothing, civicAPI "AZ"), so the district is not usable.
    - House: state plus district, with a single-seat state's at-large district
      folded onto district 01 (AP "DE-01", civicAPI "DE-AL"; those states have
      no separate district 1).
    - Ballot measures: None. The feeds name them differently ("Alabama 4:
      Require citizenship to vote" vs "Alabama Amendment 4") and the numbers
      collide, so no label joins; measures stay keyed by feed id.

    ``static/index.html`` mirrors this rule in JavaScript; keep them equal.
    """
    race_type = row.get("type")
    state = (row.get("state") or "").upper()
    if race_type == aggregate.SENATE_TYPE:
        return f"senate|{state}"
    if race_type == aggregate.GOVERNOR_TYPE:
        return f"governor|{state}"
    if race_type == aggregate.HOUSE_TYPE:
        district = (row.get("district") or "").upper()
        if district.endswith("-AL"):
            district = district[:-3] + "-01"
        return f"house|{state}|{district}"
    return None


def _key(row):
    """Ledger key for one row: its identity, or its feed id when unordered."""
    identity = race_identity(row)
    if identity is not None:
        return identity
    race_id = row.get("id")
    return str(race_id) if race_id is not None else None


def _read_at(path):
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return None
    calls = raw.get("calls") if isinstance(raw, dict) else None
    if not isinstance(calls, dict):
        return None
    return {
        "started_epoch": float(raw.get("started_epoch") or 0),
        "calls": {str(k): float(v or 0) for k, v in calls.items()},
    }


def _read():
    return _read_at(LOG_PATH)


def _write(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = LOG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1, sort_keys=True)
    os.replace(tmp, LOG_PATH)


def seed_from_fixture():
    """Merge the committed call history into the ledger.

    The seed is merged, never copied over: max() keeps an existing stamp, so a
    ledger that already orders its calls keeps its own times and only gains the
    history it is missing. That also covers a ledger written under an older
    keying rule, whose stamps no live row can reach; without the merge such a
    build would report every ordered call as made before tracking began.
    Anything missing from the seed was called after the seed was committed, so
    a build stamps it instead of leaving every race unordered.

    Returns True only when the merge changed the ledger.
    """
    global _CACHE
    seed = _read_at(SEED_PATH)
    if not seed or not any(seed["calls"].values()):
        return False
    with _LOCK:
        current = _CACHE if _CACHE is not None else _read()
        calls = dict(seed["calls"])
        started = seed["started_epoch"]
        if current:
            for key, stamp in current["calls"].items():
                calls[key] = max(calls.get(key, 0.0), stamp)
            started = min(started, current["started_epoch"])
        if current and calls == current["calls"] and started == current["started_epoch"]:
            _CACHE = current
            return False
        merged = {"started_epoch": started, "calls": calls}
        _CACHE = merged
        _write(merged)
        return True


def observe(rows, epoch=None):
    """Stamp every row first seen called and return ``{started_epoch, calls}``."""
    global _CACHE
    now = float(epoch if epoch is not None else time.time())
    with _LOCK:
        state = _CACHE if _CACHE is not None else _read()
        fresh = state is None
        if fresh:
            state = {"started_epoch": now, "calls": {}}
        learned = False
        for row in rows:
            if not row.get("called"):
                continue
            key = _key(row)
            if key is None:
                continue
            # A ledger written before calls were keyed by identity holds this
            # race's stamp under its feed id. Carry it forward instead of
            # losing a real observed time; the seed only reaches back to the
            # moment it was committed.
            legacy = str(row.get("id") or "")
            if key != legacy and legacy in state["calls"]:
                state["calls"][key] = max(state["calls"].get(key, 0.0),
                                          state["calls"].pop(legacy))
                learned = True
            if key not in state["calls"]:
                state["calls"][key] = 0.0 if now <= state["started_epoch"] + SETTLE_SECONDS else now
                learned = True
        _CACHE = state
        if fresh or learned:
            _write(state)
        return {"started_epoch": state["started_epoch"], "calls": dict(state["calls"])}


def last_by_section(board, log):
    """Pick the most recently observed call in each board section."""
    calls = log.get("calls") or {}
    out = {}
    for name in SECTIONS:
        rows = [r for r in board.get(name) or [] if r.get("called") and r.get("winner")]
        if not rows:
            out[name] = None
            continue
        stamped = [r for r in rows if calls.get(_key(r), 0) > 0]
        if stamped:
            row = max(stamped, key=lambda r: (calls[_key(r)], r.get("reporting") or 0,
                                              r.get("total_votes") or 0, str(r.get("id") or "")))
            seen = calls[_key(row)]
        else:
            row = max(rows, key=lambda r: (r.get("reporting") or 0, r.get("total_votes") or 0,
                                           str(r.get("id") or "")))
            seen = 0.0
        winner = row["winner"]
        out[name] = {
            "id": row["id"],
            "name": row.get("name"),
            "state": row.get("state"),
            "district": row.get("district"),
            "type": row.get("type"),
            "reporting": row.get("reporting") or 0,
            "known": bool(seen),
            "epoch": seen or None,
            "winner": {
                "name": winner.get("name"),
                "party": winner.get("party"),
                "group": winner.get("group"),
            },
        }
    out["started_epoch"] = log.get("started_epoch") or None
    return out
