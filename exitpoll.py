"""Read NBC News's national exit poll.

The exit poll page at
https://www.nbcnews.com/politics/2026-elections/exit-polls is served by the
same Firecracker API as the results pages. One document holds everything:

``nationalExitPollData``
    One entry per voter group NBC cuts the poll by (all voters, race, gender,
    education, age, when they voted). Each carries the ballot question split
    for Democrat and Republican and the composition share of every answer.

``nationalExitPollCMSData`` / ``page``
    The poll's phase, the text shown before polls close, the consortium
    methodology and the pollster credit.

The adapter flattens that into one stable shape: groups in the order NBC
publishes them, questions numbered in feed order, and every answer carrying
its share of the group plus the Democrat and Republican percentages. The
feed repeats question titles (two "Age" cuts, three "Income" cuts), so a
``variant`` counter keeps them apart without inventing new titles.

Percentages are the answer to "how did you vote for U.S. House today", not
national vote shares, and they are not vote counts. Nothing here is
interpolated: a missing value stays null.
"""

import json
import re
import socket
import time
import urllib.error
import urllib.request

SOURCE_URL = (
    "https://www.nbcnews.com/firecracker/api/v2/national-results/"
    "2026-elections/exit-polls"
)
PAGE_URL = "https://www.nbcnews.com/politics/2026-elections/exit-polls"
REFERER = PAGE_URL
USER_AGENT = "USMidtermTracker/1.0 (local election-night aggregator)"
POLLSTER = "SSRS for the National Election Pool"

_PCT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*%\s*$")
_PARTY_ALIASES = {"dem": "dem", "d": "dem", "gop": "rep", "rep": "rep", "r": "rep"}
_TAG_RE = re.compile(r"<[^>]+>")
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _share(text):
    """Parse "47%" into 47. Anything else becomes None."""
    match = _PCT_RE.match(text or "")
    if not match:
        return None
    value = float(match.group(1))
    return int(value) if value.is_integer() else value


def _plain_text(raw):
    """Strip the markup the CMS embeds in credit and source strings."""
    if not raw:
        return ""
    text = _TAG_RE.sub(" ", raw)
    text = _MD_BOLD_RE.sub(r"\1", text)
    text = " ".join(text.split())
    # The CMS prefixes the credit with its own "Source:" label; the panel
    # already says where the figure comes from, twice would read as a typo.
    return re.sub(r"^(?i:source)\s*:\s*", "", text)


def _party_split(values, candidates):
    """Pair one answer's values with the Democrat and Republican candidates.

    The feed lists values in candidate order and repeats the candidate colour
    on each value, so position is authoritative and colour is the check. If a
    row does not line up positionally, fall back to matching colours.
    """
    colors = [str(c.get("color", "")).lstrip("#").upper() for c in candidates]
    if len(values) == len(candidates) and all(
        str(v.get("color", "")).lstrip("#").upper() == color
        for v, color in zip(values, colors)
    ):
        pairs = list(zip(candidates, values))
    else:
        pairs = []
        for candidate, color in zip(candidates, colors):
            match = next(
                (v for v in values
                 if str(v.get("color", "")).lstrip("#").upper() == color),
                None,
            )
            if match is not None:
                pairs.append((candidate, match))

    split = {"dem": None, "rep": None}
    for candidate, value in pairs:
        party = _PARTY_ALIASES.get(str(candidate.get("party", "")).lower())
        if party in split:
            # The feed writes -1 for "no answer in this group" (a man cannot
            # be in the Women cut); -1 is not a percentage.
            raw = value.get("value")
            split[party] = raw if isinstance(raw, (int, float)) and raw >= 0 else None
    return split


def _normalise_question(raw_question, qid, candidates):
    answers = []
    for raw_answer in raw_question.get("answers") or []:
        split = _party_split(raw_answer.get("values") or [], candidates)
        answers.append({
            "label": (raw_answer.get("label") or "").strip(),
            "share": _share(raw_answer.get("percent")),
            "dem": split["dem"],
            "rep": split["rep"],
        })
    return {
        "id": qid,
        "question": (raw_question.get("question") or "").strip(),
        "variant": 1,
        "answers": answers,
    }


def _number_repeats(questions):
    """Give repeated titles a 1-based variant so the UI can tell them apart."""
    seen = {}
    for question in questions:
        name = question["question"]
        seen[name] = seen.get(name, 0) + 1
        question["variant"] = seen[name]
    return questions


def normalize(raw, fetched_at=None):
    """Rewrite the Firecracker document into the payload the page reads."""
    page = raw.get("page") or {}
    meta = raw.get("nationalExitPollCMSData") or {}
    groups_raw = raw.get("nationalExitPollData") or []

    candidates = []
    for group in groups_raw:
        polls = (group.get("polls") or {})
        for candidate in polls.get("candidates") or []:
            party = _PARTY_ALIASES.get(str(candidate.get("party", "")).lower())
            if party and party not in {c["party"] for c in candidates}:
                candidates.append({
                    "party": party,
                    "label": candidate.get("label") or party,
                    "color": candidate.get("colorHex")
                    or ("#" + candidate.get("color") if candidate.get("color") else None),
                })
        if candidates:
            break

    subsets = []
    not_ready = False
    for group in groups_raw:
        polls = group.get("polls") or {}
        if polls.get("resultsNotYetIn") or polls.get("showPollsNotClosedText"):
            not_ready = True
        questions = [
            _normalise_question(question, index + 1, candidates)
            for index, question in enumerate(polls.get("polls") or [])
        ]
        _number_repeats(questions)
        subsets.append({
            "code": group.get("code"),
            "title": (group.get("title") or "").strip(),
            "last_updated": polls.get("lastUpdated"),
            "questions": questions,
        })

    has_values = any(
        answer["dem"] is not None or answer["rep"] is not None
        for subset in subsets
        for question in subset["questions"]
        for answer in question["answers"]
    )

    phase = meta.get("currentPhase")
    note = meta.get("pollsNotClosedText")
    if not subsets:
        note = note or "The feed carried no voter groups."
    if not has_values and not note:
        note = "The feed carried no percentages yet."

    return {
        "source": "NBC News national exit poll",
        "source_url": SOURCE_URL,
        "page_url": PAGE_URL,
        "pollster": POLLSTER,
        "credit": _plain_text((page.get("source") or {}).get("sourceText")) or POLLSTER,
        "methodology": _plain_text(page.get("description")),
        "election": "2026 general",
        "fetched_at": fetched_at or time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "feed_last_modified": raw.get("lastModified"),
        "poll_last_updated": next(
            (s["last_updated"] for s in subsets if s["last_updated"]), None),
        "phase": phase,
        "ready": has_values and not not_ready,
        "note": note,
        "candidates": candidates,
        "subsets": subsets,
    }


def fetch_raw(timeout=12, attempts=2):
    """GET the exit poll document, retrying timeouts.

    Election-night traffic makes this endpoint slow rather than closed, so a
    timeout gets one more try. HTTP errors surface immediately.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Referer": REFERER,
    }
    last_error = None
    for attempt in range(attempts):
        request = urllib.request.Request(SOURCE_URL, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
            return json.loads(body.decode("utf-8"))
        except (socket.timeout, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise last_error


def refresh(timeout=12, attempts=2):
    """Fetch and normalize in one step. Raises on an unreachable feed."""
    return normalize(fetch_raw(timeout=timeout, attempts=attempts))
