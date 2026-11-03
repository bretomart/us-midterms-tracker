"""Poll closing schedule for the November 3, 2026 general election.

Single source of truth for "when can I expect numbers here". The browser never
hardcodes a copy of this table; the server ships it inside the board payload.

Times are minutes past midnight Eastern of 2026-11-03. Eastern is EST (UTC-5)
all night, because clocks fell back on 2026-11-01. Times after midnight carry
into 2026-11-04 and are expressed as 1440 + offset, so one integer comparison
tells whether a jurisdiction has finished closing.

Each entry has two fields that matter for accuracy:
- ``first``: when the earliest polling places in the jurisdiction close.
- ``last``: when the last polling places close. A statewide result is not
  possible before ``last``, and outlets withhold it until then.

Provenance. Closing hours come from the state election office document or
statute named in ``src``, cross-checked on 2026-11-03 against the AP
state-by-state guide ("When do polls close and when will election results come
in?", published 2026-11-03) and the Election Wrld poll-closing list, which
links every hour to the office document. Where two sources disagree, the
disagreement is recorded in ``disputed`` and the UI shows the caveat instead of
a bare time. Jurisdictions with ``verified=False`` could not be confirmed
against a 2026 official source; the UI labels them "unconfirmed" and shows no
time.

Voters in line when polls close may still vote in every state, so results
follow the closing time rather than arriving at it.
"""

import datetime
import time

ELECTION_DATE = datetime.date(2026, 11, 3)
ET_UTC_OFFSET = -5 * 3600  # EST, in effect from 2026-11-01
MIDNIGHT_ET = datetime.datetime(
    2026, 11, 3, 0, 0,
    tzinfo=datetime.timezone(datetime.timedelta(seconds=ET_UTC_OFFSET)))
MIDNIGHT_EPOCH = MIDNIGHT_ET.timestamp()

# The feed's national chamber row is a rollup, not a jurisdiction with polls.
NATIONAL_CODE = "US"

JURISDICTIONS = {
    "AL": dict(name="Alabama", first=1200, last=1200,
               src="sos.alabama.gov 2026 Poll Worker Guide", note="7:00 p.m. CST."),
    "AK": dict(name="Alaska", first=1440, last=1500,
               src="elections.alaska.gov",
               note="Most of the state 8:00 p.m. AKST; western Aleutian Islands "
                    "8:00 p.m. HST."),
    "AZ": dict(name="Arizona", first=1260, last=1260, src="A.R.S. §16-565",
               note="7:00 p.m. MST. The state holds results until 10:00 p.m. ET."),
    "AR": dict(name="Arkansas", first=1230, last=1230,
               src="sos.arkansas.gov 2026 Election Calendar", note="7:30 p.m. CST."),
    "CA": dict(name="California", first=1380, last=1380,
               src="2026 California voter information guide",
               note="8:00 p.m. PST. All-mail; ballots postmarked by Election Day "
                    "count if received by Nov 10."),
    "CO": dict(name="Colorado", first=1260, last=1260,
               src="coloradosos.gov in-person voting release", note="7:00 p.m. MST."),
    "CT": dict(name="Connecticut", first=1200, last=1200,
               src="portal.ct.gov 2026 Election Calendar"),
    "DE": dict(name="Delaware", first=1200, last=1200,
               src="Delaware 2026 Voter Information Brochure"),
    "DC": dict(name="District of Columbia", first=1200, last=1200,
               src="dcboe.org 2026 general notice"),
    "FL": dict(name="Florida", first=1140, last=1200,
               src="dos.fl.gov election day voting FAQ",
               note="Most of the state 7:00 p.m. ET; the western Panhandle "
                    "8:00 p.m. ET (7:00 p.m. CST)."),
    "GA": dict(name="Georgia", first=1140, last=1140,
               src="georgia.gov election day notice"),
    "HI": dict(name="Hawaii", first=1440, last=1440,
               src="HRS §11-131; Honolulu Office of Elections", note="7:00 p.m. HST."),
    "ID": dict(name="Idaho", first=1320, last=1380, src="voteidaho.gov election day notice",
               note="Most of the state 8:00 p.m. MST; northern Idaho 8:00 p.m. PST."),
    "IL": dict(name="Illinois", first=1200, last=1200,
               src="elections.il.gov voters guide", note="7:00 p.m. CST."),
    "IN": dict(name="Indiana", first=1080, last=1140,
               src="2026 Indiana election calendar; in.gov voter portal",
               note="Most of the state 6:00 p.m. ET; northwest and southwest "
                    "counties 7:00 p.m. ET (6:00 p.m. CST)."),
    "IA": dict(name="Iowa", first=1260, last=1260, src="Iowa Code §49.73",
               note="8:00 p.m. CST.",
               disputed="The CBS News 2026-11-03 schedule listed Iowa at "
                        "10:00 p.m. ET. Iowa Code §49.73 and the Secretary of "
                        "State results page say 8:00 p.m. CST, which is "
                        "9:00 p.m. ET."),
    "KS": dict(name="Kansas", first=1200, last=1320, src="sos.ks.gov voter information",
               note="Most counties close between 8:00 and 9:00 p.m. ET; Sherman, "
                    "Wallace, Greeley and Hamilton between 9:00 and 10:00 p.m. ET. "
                    "Each county sets its own hour."),
    "KY": dict(name="Kentucky", first=1080, last=1140, src="elect.ky.gov election day FAQ",
               note="Central and eastern Kentucky 6:00 p.m. ET; western Kentucky "
                    "7:00 p.m. ET (6:00 p.m. CST)."),
    "LA": dict(name="Louisiana", first=1260, last=1260, src="sos.la.gov election day FAQs",
               note="8:00 p.m. CST. A candidate needs a majority, or the top two "
                    "meet in a runoff."),
    "ME": dict(name="Maine", first=1200, last=1200, src="21-A M.R.S. §626"),
    "MD": dict(name="Maryland", first=1200, last=1200,
               src="elections.maryland.gov election day questions"),
    "MA": dict(name="Massachusetts", first=1200, last=1200, src="M.G.L. c.54 §64"),
    "MI": dict(name="Michigan", first=1200, last=1260, src="michigan.gov vote on election day",
               note="Most of the state 8:00 p.m. ET; Gogebic, Iron, Dickinson and "
                    "Menominee counties 9:00 p.m. ET (8:00 p.m. CST)."),
    "MN": dict(name="Minnesota", first=1260, last=1260, src="sos.mn.gov 2026 polling place posters",
               note="8:00 p.m. CST."),
    "MS": dict(name="Mississippi", first=1200, last=1200,
               src="sos.ms.gov 2026 Elections Calendar", note="7:00 p.m. CST."),
    "MO": dict(name="Missouri", first=1200, last=1200, src="sos.mo.gov how to vote",
               note="7:00 p.m. CST."),
    "MT": dict(name="Montana", first=1320, last=1320, src="MCA 13-1-603", note="8:00 p.m. MST."),
    "NE": dict(name="Nebraska", first=1260, last=1260,
               src="sos.nebraska.gov 2026 Election Calendar",
               note="8:00 p.m. CST; western counties 7:00 p.m. MST.",
               disputed="The CBS News 2026-11-03 schedule listed Nebraska at "
                        "10:00 p.m. ET. The Nebraska Secretary of State calendar "
                        "says 8:00 p.m. CST, which is 9:00 p.m. ET."),
    "NV": dict(name="Nevada", first=1260, last=1320, src="NRS 293.255; silverstateelection.nv.gov",
               note="Most of the state 7:00 p.m. PST (10:00 p.m. ET); West "
                    "Wendover 7:00 p.m. MST (9:00 p.m. ET)."),
    "NH": dict(name="New Hampshire", first=1140, last=1200, src="RSA 659:4; sos.nh.gov",
               note="Each town sets its own hour, no earlier than 7:00 p.m. ET. "
                    "Outlets hold state results until 8:00 p.m. ET."),
    "NJ": dict(name="New Jersey", first=1200, last=1200, src="nj.gov 2026 how-to-vote flyer"),
    "NM": dict(name="New Mexico", first=1260, last=1260,
               src="sos.nm.gov 2026 general election dates", note="7:00 p.m. MST."),
    "NY": dict(name="New York", first=1260, last=1260,
               src="N.Y. Election Law §8-100; elections.ny.gov"),
    "NC": dict(name="North Carolina", first=1170, last=1170, src="ncsbe.gov 2026 reporter's primer"),
    "ND": dict(name="North Dakota", first=1200, last=1380, src="sos.nd.gov 2026 media info",
               note="Most of the state closes between 8:00 and 10:00 p.m. ET; "
                    "southwestern counties between 9:00 and 11:00 p.m. ET. Each "
                    "county sets its own hour."),
    "OH": dict(name="Ohio", first=1170, last=1170, src="ORC 3501.32"),
    "OK": dict(name="Oklahoma", first=1200, last=1200, src="oklahoma.gov elections FAQ",
               note="7:00 p.m. CST."),
    "OR": dict(name="Oregon", first=1320, last=1380, src="sos.oregon.gov elections",
               note="All-mail. Most of the state 8:00 p.m. PST; most of Malheur "
                    "County 8:00 p.m. MST."),
    "PA": dict(name="Pennsylvania", first=1200, last=1200, src="pa.gov upcoming elections"),
    "RI": dict(name="Rhode Island", first=1200, last=1200, src="vote.sos.ri.gov 2026 election calendar"),
    "SC": dict(name="South Carolina", first=1140, last=1140, src="scvotes.gov 2026 voter prep"),
    "SD": dict(name="South Dakota", first=1200, last=1260, src="sos.sd.gov",
               note="Most of the state 7:00 p.m. CST; western South Dakota "
                    "7:00 p.m. MST."),
    "TN": dict(name="Tennessee", first=1200, last=1200, src="T.C.A. §2-9-105; elections.tn.gov",
               note="7:00 p.m. local, which is 8:00 p.m. ET in both time zones.",
               disputed="The CBS News 2026-11-03 schedule listed Tennessee at "
                        "9:00 p.m. ET. T.C.A. §2-9-105 closes polls at 7 p.m. "
                        "local, which is 8:00 p.m. ET."),
    "TX": dict(name="Texas", first=1200, last=1260, src="texaselections.gov",
               note="Most of the state 7:00 p.m. CST; El Paso and Hudspeth "
                    "counties 7:00 p.m. MST."),
    "UT": dict(name="Utah", first=1320, last=1320, src="electionresults.utah.gov",
               note="Mail ballots and drop boxes close 8:00 p.m. MST."),
    "VT": dict(name="Vermont", first=1140, last=1140, src="sos.vermont.gov polling places"),
    "VA": dict(name="Virginia", first=1140, last=1140, src="elections.virginia.gov"),
    "WA": dict(name="Washington", first=1380, last=1380, src="sos.wa.gov dates and deadlines",
               note="All-mail; ballots postmarked by Election Day count if "
                    "received by Nov 23."),
    "WV": dict(name="West Virginia", first=1170, last=1170, src="sos.wv.gov election FAQs"),
    "WI": dict(name="Wisconsin", first=1260, last=1260, src="Wis. Stat. §6.36(1)(a)",
               note="8:00 p.m. CST. No statewide results feed; counties report "
                    "separately."),
    "WY": dict(name="Wyoming", first=1260, last=1260, src="sos.wyo.gov 2026 Election Calendar",
               note="7:00 p.m. MST."),
    # Territories: no 2026 official source confirmed, so no time is asserted.
    "AS": dict(name="American Samoa", first=None, last=None, verified=False,
               src="not verified for 2026"),
    "GU": dict(name="Guam", first=None, last=None, verified=False,
               src="not verified for 2026"),
    "MP": dict(name="Northern Mariana Islands", first=None, last=None, verified=False,
               src="not verified for 2026"),
    "PR": dict(name="Puerto Rico", first=None, last=None, verified=False,
               src="not verified for 2026"),
    "VI": dict(name="U.S. Virgin Islands", first=None, last=None, verified=False,
               src="not verified for 2026"),
}

for _entry in JURISDICTIONS.values():
    _entry.setdefault("verified", True)
    _entry.setdefault("disputed", None)
    _entry.setdefault("note", None)
    _entry.setdefault("src", None)


def jurisdiction(code):
    """Return the schedule entry for a province code, or None."""
    return JURISDICTIONS.get(code)


def minutes_to_label(minutes):
    """Format minutes past midnight ET of 2026-11-03 as a clock label."""
    if minutes is None:
        return None
    day, rest = divmod(int(minutes), 1440)
    h, m = divmod(rest, 60)
    suffix = " PM" if h >= 12 else " AM"
    hour12 = h % 12 or 12
    label = f"{hour12}:{m:02d}{suffix} ET"
    if day:
        label += f" Nov {ELECTION_DATE.day + day}"
    return label


def minutes_to_epoch(minutes):
    """Absolute epoch for a schedule minute, so clients need no timezone math."""
    if minutes is None:
        return None
    return MIDNIGHT_EPOCH + int(minutes) * 60


def et_now_index(epoch=None):
    """Minutes past midnight ET of 2026-11-03. Negative before, 1440+ after."""
    if epoch is None:
        epoch = time.time()
    struct = time.gmtime(epoch + ET_UTC_OFFSET)
    day = datetime.date(struct.tm_year, struct.tm_mon, struct.tm_mday)
    return (day - ELECTION_DATE).days * 1440 + struct.tm_hour * 60 + struct.tm_min


def et_clock_label(epoch=None):
    """Eastern wall clock for an epoch, e.g. '9:41 PM EST'."""
    if epoch is None:
        epoch = time.time()
    struct = time.gmtime(epoch + ET_UTC_OFFSET)
    return time.strftime("%I:%M %p", struct).lstrip("0") + " EST"


def close_status(code, now_index=None):
    """One of closed, partial, upcoming, unscheduled for a jurisdiction."""
    entry = jurisdiction(code)
    if entry is None or entry.get("last") is None:
        return "unscheduled"
    if now_index is None:
        now_index = et_now_index()
    if now_index >= entry["last"]:
        return "closed"
    if entry.get("first") is not None and now_index >= entry["first"]:
        return "partial"
    return "upcoming"


def attach(races, now_index=None, epoch=None):
    """Add closing-schedule fields to normalised races, in place.

    Adds close_first, close_last, close_label, close_epoch, close_note,
    close_src, close_disputed, close_verified, polls_closed, close_state.
    """
    if now_index is None:
        now_index = et_now_index(epoch)
    for race in races:
        if race.get("state") == NATIONAL_CODE:
            race.update({
                "close_first": None, "close_last": None, "close_label": None,
                "close_epoch": None,
                "close_note": "Rollup of the state rows; it fills in as the "
                              "states report.",
                "close_src": None, "close_disputed": None, "close_verified": True,
                "polls_closed": False, "close_state": "rollup",
            })
            continue
        entry = jurisdiction(race.get("state"))
        if entry is None:
            race.update({
                "close_first": None, "close_last": None, "close_label": None,
                "close_epoch": None, "close_note": None, "close_src": None,
                "close_disputed": None, "close_verified": False,
                "polls_closed": False, "close_state": "unscheduled",
            })
            continue
        first, last = entry.get("first"), entry.get("last")
        race.update({
            "close_first": first,
            "close_last": last,
            "close_label": minutes_to_label(last),
            "close_epoch": minutes_to_epoch(last),
            "close_note": entry.get("note"),
            "close_src": entry.get("src"),
            "close_disputed": entry.get("disputed"),
            "close_verified": entry.get("verified"),
            "polls_closed": last is not None and now_index >= last,
            "close_state": close_status(race.get("state"), now_index),
        })
    return races


def waves(codes, now_index=None, epoch=None):
    """Build the closing-wave strip for the jurisdictions actually in the feed.

    One bucket per distinct closing minute, drawn from both ``first`` and
    ``last``, because election night has two different events at an hour: the
    first precincts report, and the last precincts close. ``opens`` lists the
    jurisdictions whose first data can appear at that minute; ``closes`` lists
    the ones that are finished, which is when a statewide result is possible.

    The synthetic national row (province ``US``) is excluded: it has no polls.
    """
    if now_index is None:
        now_index = et_now_index(epoch)
    present = {c: n for c, n in codes.items() if c != NATIONAL_CODE}
    buckets = {}
    unscheduled = []
    for code, count in sorted(present.items()):
        entry = jurisdiction(code)
        if entry is None or entry.get("last") is None:
            unscheduled.append(code)
            continue
        first, last = entry.get("first"), entry["last"]
        for key, group in (("first", "opens"), ("last", "closes")):
            at = entry.get(key)
            if at is None:
                continue
            bucket = buckets.setdefault(at, {
                "at": at,
                "label": minutes_to_label(at),
                "epoch": minutes_to_epoch(at),
                "opens": [],
                "closes": [],
                "races_open": 0,
                "races_close": 0,
                "unverified": [],
                "disputed": [],
            })
            tag = code if first == last else f"{code} {'first' if key == 'first' else 'last'}"
            bucket[group].append({
                "code": code, "label": tag, "races": count,
                "note": entry.get("note"), "src": entry.get("src"),
            })
            bucket["races_open" if group == "opens" else "races_close"] += count
            if group == "closes":
                if entry.get("verified") is False:
                    bucket["unverified"].append(code)
                if entry.get("disputed"):
                    bucket["disputed"].append({"code": code, "note": entry["disputed"]})

    out = []
    for at in sorted(buckets):
        bucket = buckets[at]
        for key in ("opens", "closes"):
            bucket[key].sort(key=lambda item: item["code"])
        bucket["closed"] = now_index >= at
        bucket["countdown_minutes"] = None if now_index >= at else int(at - now_index)
        bucket["next"] = False
        out.append(bucket)
    for bucket in out:
        if not bucket["closed"]:
            bucket["next"] = True
            break
    if unscheduled:
        out.append({
            "at": None, "label": "Unconfirmed", "epoch": None,
            "opens": [], "closes": [{"code": c, "label": c, "races": present[c],
                                     "note": None, "src": None}
                                    for c in sorted(unscheduled)],
            "races_open": 0, "races_close": sum(present[c] for c in unscheduled),
            "unverified": sorted(unscheduled), "disputed": [],
            "closed": False, "next": False, "countdown_minutes": None,
        })
    return out


def schedule_block(now_index=None, epoch=None):
    """Payload block describing the schedule itself and its caveats."""
    if epoch is None:
        epoch = time.time()
    if now_index is None:
        now_index = et_now_index(epoch)
    return {
        "election_date": ELECTION_DATE.isoformat(),
        "timezone": "America/New_York (EST, UTC-5 after the Nov 1 fall back)",
        "midnight_epoch": MIDNIGHT_EPOCH,
        "now_epoch": epoch,
        "now_minutes_et": now_index,
        "now_label_et": et_clock_label(epoch),
        "note": "Voters in line when polls close may still vote, so results "
                "follow the closing time rather than arriving at it.",
        "provenance": "Closing hours come from state election office documents "
                      "and statutes, cross-checked on 2026-11-03 against the AP "
                      "state-by-state guide and the Election Wrld office-linked "
                      "list.",
        "disputed": {
            code: entry["disputed"]
            for code, entry in sorted(JURISDICTIONS.items()) if entry.get("disputed")
        },
        "unverified": sorted(
            code for code, entry in JURISDICTIONS.items() if not entry.get("verified")),
    }
