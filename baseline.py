"""Pre-election composition of the bodies being elected on 2026-11-03.

Election night arithmetic needs a starting point: "Democrats are at 44 seats"
only means anything against the 47 they held. Every number here is a fact a
third party published, not an assumption of ours, so each block carries its own
source and as-of date. The server ships these inside the payload; the browser
never hardcodes a copy.

Verified on 2026-11-03 against:
- Ballotpedia "Election results, 2026: U.S. Senate" and "Election results, 2026:
  U.S. House" (ballotpedia.org), which state the partisan breakdown heading into
  the election.
- The civicAPI national rollup rows (race 87528 Senate, race 87524 House), which
  report the seats not up for election.
- Ballotpedia "Gubernatorial elections, 2026" for the governorship split.

Where the feed and these sources disagree, aggregate.conflicts reports it in the
banner instead of picking a side.
"""

# Chamber: majority threshold, total seats, and the composition before the
# election. "held" counts seats a party already owns; "contested" is how many of
# those seats appear on the 2026-11-03 ballot.
SENATE = {
    "total_seats": 100,
    "majority": 51,
    "contested": 35,
    # 53 R, 45 D, 2 I before the election. Of the 35 seats up, 22 are held by
    # Republicans, 11 by Democrats and 2 by the independents, so no independent
    # seat is parked outside tonight's contest. Holdover below is 45-11 D, 53-22
    # R, 2-2 I, which matches the seats-not-up figures the feed's rollup row
    # reports (34 D, 31 R).
    "holdover": {"D": 34, "R": 31, "O": 0},
    "held_before": {"D": 45, "R": 53, "O": 2},
    "note": "Two independents caucus with the Democrats for organizational votes.",
    "source": "Ballotpedia Election results, 2026: U.S. Senate; civicAPI race 87528",
    "as_of": "2026-11-03",
}

HOUSE = {
    "total_seats": 435,
    "majority": 218,
    "contested": 435,
    # Ballotpedia: "Republicans hold a 218-214 majority in the U.S. House, with
    # one independent who caucuses and two vacancies." The independent is
    # grouped as O. Two seats are vacant, so 433 members sit today.
    "held_before": {"D": 214, "R": 218, "O": 1},
    "vacant": 2,
    "note": "One independent caucuses with Republicans; two seats are vacant.",
    "source": "Ballotpedia Election results, 2026: U.S. House (218 R, 214 D, 1 I, 2 vacant)",
    "as_of": "2026-11-03",
}

GOVERNOR = {
    "total_offices": 50,
    "majority": 26,
    # 36 state governorships appear on the ballot; the feed also carries Guam,
    # the Northern Mariana Islands and the US Virgin Islands, which are not part
    # of the 50-state count.
    "contested_states": 36,
    "held_before": {"D": 24, "R": 26, "O": 0},
    "note": "Democrats need to net two governorships for a majority of the 50 states.",
    "source": "Ballotpedia Gubernatorial elections, 2026 (26 R, 24 D as of November 2026)",
    "as_of": "2026-11-03",
}


def block():
    """Machine-readable baseline for the payload, with provenance intact."""
    return {
        "senate": SENATE,
        "house": HOUSE,
        "governor": GOVERNOR,
        "provenance": "Composition figures come from Ballotpedia pages current as "
                      "of 2026-11-03 and are cross-checked against the civicAPI "
                      "national rollup rows. Territories are excluded from the "
                      "50-state and 100-seat counts.",
    }
