#!/usr/bin/env python3
"""Build the static GitHub Pages copy of the dashboard.

The dashboard reads /api/races and /api/news from the local server. GitHub
Pages serves files and runs no Python, so this script performs the same pull
and aggregation the server performs at runtime, then writes both payloads
next to a copy of the page. The page tries the API first and falls back to
these files, so one HTML file works in both places.

The build exits non-zero unless the results genuinely came from a live
results feed (AP first, civicAPI as the fallback source), so a bad upstream
minute cannot replace a good deployment with empty data.

Usage:
    python3 export_static.py --out dist
"""
import argparse
import json
import os
import sys
import time

import call_log
import server

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, separators=(",", ":"))
    return os.path.getsize(path)


PAGE_MARKER = '<html lang="en">'
SNAPSHOT_OPEN = '<html lang="en" data-mode="snapshot">'


def _copy_page(src, dest):
    """Copy the page, marked as a published snapshot.

    The page reads the mark to skip its /api/* probe, which a static host
    answers with a 404. Without it every load pays two failed requests in the
    network panel and waits out the miss before reading data/.
    """
    with open(src, "r", encoding="utf-8") as fh:
        page = fh.read()
    if PAGE_MARKER not in page:
        raise SystemExit(f"refusing to publish: {src} lost its <html> opener")
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(page.replace(PAGE_MARKER, SNAPSHOT_OPEN, 1))


def build(out_dir):
    # A call stamp cannot be re-derived from the feed, so a build whose cache
    # is cold starts from the committed ledger instead of an empty one.
    if call_log.seed_from_fixture():
        print("[CALL LOG] ledger had no call times; seeded them from fixtures/call_log.json")
    # The fixture warm-up only matters for the failure path: it gives the
    # status check something to reject, rather than an empty payload.
    server.load_from_fixtures("FIXTURE-WARMUP")
    server.refresh_from_upstream()

    with server._STATE_LOCK:
        payload = server._STATE["payload"]
        status = server._STATE["source_status"]
        upstream_error = server._STATE["upstream_error"]

    if status not in ("LIVE-AP", "LIVE-CIVICAPI") or not payload:
        print("refusing to publish: upstream pull failed "
              f"({status}: {upstream_error})", file=sys.stderr)
        return 1

    server.refresh_news_feeds()
    with server._NEWS_LOCK:
        news_items = list(server._NEWS_STATE["items"])
        news_providers = list(server._NEWS_STATE["providers"])
        news_fetched_at = server._NEWS_STATE["fetched_at"]

    if not news_items:
        print("refusing to publish: every news feed failed", file=sys.stderr)
        return 1

    # The exit poll is a separate upstream and a separate panel, so a failed
    # pull costs that panel and not the deployment. Never publish the local
    # warm-up fixture: it is a recording of an earlier moment, not today's poll.
    server.load_exit_polls_from_fixture()
    exit_ok = server.refresh_exit_polls()
    with server._EXIT_LOCK:
        exit_payload = server._EXIT_STATE["payload"]
        exit_error = server._EXIT_STATE["error"]
    if not exit_ok:
        print(f"warning: exit poll pull failed ({exit_error}); panel will report unavailable",
              file=sys.stderr)

    epoch = int(time.time())
    snapshot = dict(payload)
    snapshot["cache_age_seconds"] = 0.0
    snapshot["snapshot_epoch"] = epoch
    news = {
        "fetched_at": news_fetched_at,
        "cache_age_seconds": 0.0,
        "snapshot_epoch": epoch,
        "providers": news_providers,
        "items": news_items,
    }

    out_dir = os.path.abspath(out_dir)
    data_dir = os.path.join(out_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    _copy_page(os.path.join(BASE_DIR, "static", "index.html"),
               os.path.join(out_dir, "index.html"))
    # Nothing here needs a site generator, and data/ must ship verbatim.
    with open(os.path.join(out_dir, ".nojekyll"), "w", encoding="utf-8"):
        pass
    for static_file in ("robots.txt", "sitemap.xml"):
        src_path = os.path.join(BASE_DIR, "static", static_file)
        if os.path.exists(src_path):
            with open(src_path, "r", encoding="utf-8") as rf, open(os.path.join(out_dir, static_file), "w", encoding="utf-8") as wf:
                wf.write(rf.read())

    exitpolls = None
    if exit_ok and exit_payload:
        exitpolls = dict(exit_payload)
        exitpolls["cache_age_seconds"] = 0.0
        exitpolls["snapshot_epoch"] = epoch
        exitpolls["upstream_error"] = None

    races_size = _write_json(os.path.join(data_dir, "races.json"), snapshot)
    news_size = _write_json(os.path.join(data_dir, "news.json"), news)

    board = snapshot.get("board") or {}
    rows = sum(len(board.get(key) or []) for key in ("senate", "house", "governor", "measures"))
    feeds_ok = sum(1 for p in news_providers if p.get("status") == "OK")
    print(f"wrote {out_dir}")
    print("  index.html")
    print(f"  data/races.json  {races_size:,} bytes  {rows} board rows  {status}")
    print(f"  data/news.json   {news_size:,} bytes  {len(news_items)} headlines  "
          f"{feeds_ok}/{len(news_providers)} feeds OK")
    if exitpolls:
        exit_size = _write_json(os.path.join(data_dir, "exitpolls.json"), exitpolls)
        groups = len(exitpolls.get("subsets") or [])
        questions = sum(len(g.get("questions") or []) for g in exitpolls.get("subsets") or [])
        print(f"  data/exitpolls.json  {exit_size:,} bytes  {groups} voter groups  "
              f"{questions} questions  {exitpolls.get('poll_last_updated')}")
    else:
        print("  data/exitpolls.json  not written (upstream failed)")
    print(f"  snapshot epoch   {epoch}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Build the static GitHub Pages copy.")
    parser.add_argument("--out", default="dist", help="output directory (default: dist)")
    args = parser.parse_args()
    return build(args.out)


if __name__ == "__main__":
    sys.exit(main())
