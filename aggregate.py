"""Normalise civicAPI race payloads and compute chamber tallies.

Accuracy rules:
- A race with zero total votes is "no data", never a zero-vote leader.
- A race is "called" only when the source sets a candidate's winner flag.
- Tallies from per-race calls are compared with the feed's own running
  national seat totals and with the published pre-election baseline; any
  difference is reported, never hidden.
"""

import baseline

PARTY_GROUPS = {"Democratic": "D", "Republican": "R"}
NATIONAL_PROVINCE = "US"
HOUSE_TYPE = "House of Representatives"
SENATE_TYPE = "US Senate"
GOVERNOR_TYPE = "Governor"
MEASURE_TYPES = {"Referendum", "Proposition", "Ballot Measure"}

# The 50 states plus the District of Columbia. Territories (GU, MP, VI, AS, PR)
# are races like any other, but they never enter 50-state majority arithmetic.
STATE_CODES = frozenset(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO "
    "MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY "
    "DC".split())


def party_group(party):
    return PARTY_GROUPS.get(party, "O")


def normalise_race(raw):
    """Reduce one raw race to the fields the dashboard needs."""
    cands = []
    for c in raw.get("candidates") or []:
        cands.append({
            "name": c.get("name"),
            "party": c.get("party"),
            "group": party_group(c.get("party")),
            "votes": int(c.get("votes") or 0),
            "percent": c.get("percent") or 0,
            "winner": bool(c.get("winner")),
        })
    total = sum(c["votes"] for c in cands)
    winners = [c for c in cands if c["winner"]]
    leader = None
    if total > 0:
        top = max(c["votes"] for c in cands)
        tied = [c for c in cands if c["votes"] == top]
        leader = tied[0] if len(tied) == 1 else None
    cands.sort(key=lambda c: c["votes"], reverse=True)
    return {
        "id": raw.get("id"),
        "type": raw.get("type"),
        "name": raw.get("election_name"),
        "state": raw.get("province"),
        "district": raw.get("district"),
        "reporting": raw.get("percent_reporting") or 0,
        "total_votes": total,
        "has_data": total > 0,
        "tied": total > 0 and leader is None,
        "called": bool(winners),
        "winner": winners[0] if winners else None,
        "multiple_winners": len(winners) > 1,
        "leader": leader,
        "candidates": cands,
    }


def tally(races):
    """Count called and leading races by party group."""
    out = {"races": 0, "no_data": 0, "tied": 0,
           "called": {"D": 0, "R": 0, "O": 0},
           "leading": {"D": 0, "R": 0, "O": 0}}
    for r in races:
        out["races"] += 1
        if r["called"]:
            for w in ([r["winner"]] if not r["multiple_winners"] else [r["winner"]]):
                out["called"][w["group"]] += 1
        elif not r["has_data"]:
            out["no_data"] += 1
        elif r["tied"]:
            out["tied"] += 1
        else:
            out["leading"][r["leader"]["group"]] += 1
    return out


def feed_seats(national_raw):
    """Seat totals the feed itself reports on a national chamber race."""
    seats = {"D": 0, "R": 0, "O": 0}
    for c in national_raw.get("candidates") or []:
        seats[party_group(c.get("party"))] += int(c.get("seats") or 0)
    return seats


def control(total, majority, reporting):
    """Project chamber control from seats held plus seats called tonight.

    Returns a dict the UI reads verbatim: who leads, whether anyone has the
    majority yet, and how many seats each side still needs. It never guesses a
    winner for a race the source has not called, so an undecided chamber stays
    "undecided" until the arithmetic forces one party past the threshold.
    """
    leader = max(total, key=lambda g: total[g])
    others = [g for g in total if g != leader]
    tied = total[leader] == max(total[g] for g in others)
    out = {
        "majority": majority,
        "needed": {g: max(0, majority - total[g]) for g in total},
        "decided": total[leader] >= majority and not tied,
        "holder": None,
        "state": "undecided",
        "reporting_races": reporting,
    }
    if out["decided"]:
        out["holder"] = leader
        out["state"] = "majority"
    elif tied and total[leader] > 0:
        out["state"] = "tied"
    return out


def split_board(races):
    """Split normalised races into dashboard sections.

    The feed carries synthetic national rows (province ``US``) that roll up a
    chamber or the governorships. They are not contests, so they never enter a
    state board; they go to ``national`` keyed by chamber.
    """
    board = {"senate": [], "house": [], "governor": [], "measures": [],
             "national": {}}
    national_key = {HOUSE_TYPE: "house", SENATE_TYPE: "senate",
                    GOVERNOR_TYPE: "governor"}
    for r in races:
        t, state = r["type"], r["state"]
        if state == NATIONAL_PROVINCE:
            key = national_key.get(t)
            if key:
                board["national"][key] = r
            continue
        if t == HOUSE_TYPE:
            board["house"].append(r)
        elif t == SENATE_TYPE:
            board["senate"].append(r)
        elif t == GOVERNOR_TYPE:
            board["governor"].append(r)
        elif t in MEASURE_TYPES:
            board["measures"].append(r)
    return board


def conflicts(board, national_raw):
    """Compare per-race calls with the feed's national seat totals.

    national_raw maps "house" and "senate" to the raw national race payload.
    Returns a list of human-readable discrepancies.
    """
    found = []
    for chamber in ("house", "senate"):
        raw = national_raw.get(chamber)
        if raw is None:
            continue
        reported = feed_seats(raw)
        counted = tally(board[chamber])["called"]
        # Senate national seats are the seats not up in 2026, so they pair with
        # tonight's calls instead of duplicating them.
        if chamber == "senate":
            base = baseline.SENATE["holdover"]
            for g in ("D", "R", "O"):
                if reported[g] != base[g]:
                    found.append(
                        f"senate {g}: feed reports {reported[g]} seats not up, "
                        f"baseline says {base[g]}")
            for g in ("D", "R", "O"):
                total = reported[g] + counted[g]
                if total > baseline.SENATE["total_seats"]:
                    found.append(
                        f"senate {g}: holdover {reported[g]} plus {counted[g]} "
                        f"called exceeds 100 seats")
            continue
        for g in ("D", "R", "O"):
            if reported[g] != counted[g]:
                found.append(
                    f"{chamber} {g}: feed reports {reported[g]} seats, "
                    f"called races sum to {counted[g]}")
    for r in board["house"] + board["senate"] + board["governor"]:
        if r["multiple_winners"]:
            found.append(f"{r['name']}: more than one winner flag set")
    return found
