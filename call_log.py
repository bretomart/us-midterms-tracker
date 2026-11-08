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
    """Give the ledger the committed call history when it has none of its own.

    The seed is merged, not copied. A ledger that already orders its calls is
    left alone; a ledger whose stamps are all zero (a cold start that saw only
    calls already made) takes the seed's stamps and keeps the ids it saw.
    Anything missing from the seed was called after the seed was committed, so
    a cold build stamps it instead of leaving every race unordered.
    """
    global _CACHE
    seed = _read_at(SEED_PATH)
    if not seed or not any(seed["calls"].values()):
        return False
    with _LOCK:
        current = _CACHE if _CACHE is not None else _read()
        if current and any(current["calls"].values()):
            return False
        calls = dict(seed["calls"])
        started = seed["started_epoch"]
        if current:
            for key, stamp in current["calls"].items():
                calls[key] = max(calls.get(key, 0.0), stamp)
            started = min(started, current["started_epoch"])
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
            race_id = row.get("id")
            if race_id is None or not row.get("called"):
                continue
            key = str(race_id)
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
        stamped = [r for r in rows if calls.get(str(r["id"]), 0) > 0]
        if stamped:
            row = max(stamped, key=lambda r: (calls[str(r["id"])], r.get("reporting") or 0,
                                              r.get("total_votes") or 0, str(r.get("id") or "")))
            seen = calls[str(row["id"])]
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
