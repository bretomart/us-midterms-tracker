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
import shutil
import sys
import time

import server

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, separators=(",", ":"))
    return os.path.getsize(path)


def build(out_dir):
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
    shutil.copyfile(
        os.path.join(BASE_DIR, "static", "index.html"),
        os.path.join(out_dir, "index.html"),
    )
    # Nothing here needs a site generator, and data/ must ship verbatim.
    with open(os.path.join(out_dir, ".nojekyll"), "w", encoding="utf-8"):
        pass

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
    print(f"  snapshot epoch   {epoch}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Build the static GitHub Pages copy.")
    parser.add_argument("--out", default="dist", help="output directory (default: dist)")
    args = parser.parse_args()
    return build(args.out)


if __name__ == "__main__":
    sys.exit(main())
