#!/usr/bin/env bash
# Drives the Pages snapshot via workflow_dispatch every 5 minutes.
#
# Why: GitHub's scheduler throttles best-effort cron dispatches on public
# repos. Observed on this repo: 5 schedule runs landed of ~576 expected
# triggers in two days, none on the cron grid, while workflow_dispatch
# starts within seconds (see .github/workflows/deploy.yml comment).
#
# Modes:
#   ./run_cron.sh              one dispatch + build wait (no loop)
#   ./run_cron.sh --watch      dispatch on every 5-minute boundary, forever
#   ./run_cron.sh --once-if-idle   skip if a run is already active; for timers
#
# Failure handling: deploy.yml fails on purpose when both results feeds are
# unreachable, leaving the last good Pages deployment published. After a
# failed run this script still pings, but at most once every 30 minutes, so
# the site self-recovers when the feed heals without hammering GitHub.
#
# Setup for a persistent 5-minute loop:
#   systemd-run --user --unit=midterms-cron --on-calendar='*:0/5' \
#       ./run_cron.sh --once-if-idle
# state/cron_state tracks the failure cooldown across invocations.
set -euo pipefail

REPO="${REPO:-bretomart/us-midterms-tracker}"
WORKFLOW="deploy.yml"
BRANCH="main"
FAILURE_COOLDOWN=1800
STATE_FILE="$(dirname "$0")/state/cron_state"
SECONDS=0

latest() {
    gh run list --repo "$REPO" --workflow "$WORKFLOW" --branch "$BRANCH" \
        --limit 1 --json status,conclusion,displayTitle,startedAt \
        --jq '.[0]'
}

record_attempt() { mkdir -p "$(dirname "$STATE_FILE")" && date +%s > "$STATE_FILE"; }
last_attempt() { cat "$STATE_FILE" 2>/dev/null || echo 0; }

dispatch_and_wait() {
    echo "[$(date -u +%H:%M:%SZ)] dispatching $WORKFLOW on $BRANCH"
    gh workflow run "$WORKFLOW" --repo "$REPO" --ref "$BRANCH"
    record_attempt

    # The workflow is quick (~30s) once it starts; allow a generous window
    # for GitHub-side congestion before reporting a timeout.
    local deadline=$((SECONDS + 300)) conclusion
    while (( SECONDS < deadline )); do
        sleep 10
        conclusion=$(latest --json status,conclusion 2>/dev/null | jq -r '.conclusion // empty')
        # in_progress/queued fall through to the next poll; a conclusion
        # (success or failure) means the run finished and Pages reflects it.
        if [[ -n "$conclusion" && "$conclusion" != "null" ]]; then
            echo "[$(date -u +%H:%M:%SZ)] run finished: $conclusion"
            [[ "$conclusion" == "success" ]] || return 1
            return 0
        fi
    done
    echo "timed out waiting for a completed run (still in progress?)" >&2
    return 1
}

maybe_dispatch() {
    local now run
    run=$(latest --json status,conclusion,displayTitle,startedAt)
    local status conclusion
    status=$(jq -r '.status' <<<"$run")
    conclusion=$(jq -r '.conclusion // empty' <<<"$run")

    if [[ "$status" == in_progress || "$status" == queued ]]; then
        echo "[$(date -u +%H:%M:%SZ)] a run is already active; skipping this tick"
        return 0
    fi

    now=$(date +%s)
    if [[ "$conclusion" == "failure" ]] && (( now - $(last_attempt) < FAILURE_COOLDOWN )); then
        echo "[$(date -u +%H:%M:%SZ)] last run failed (upstream feed down?); next try in $(( FAILURE_COOLDOWN - (now - $(last_attempt)) ))s"
        return 0
    fi

    dispatch_and_wait || return 1
}

case "${1:-}" in
    --watch)
        while :; do
            maybe_dispatch || true
            # Sleep to the next :00/:05/:10... boundary.
            sleep $(( 300 - (SECONDS % 300) ))
        done
        ;;
    --once-if-idle) maybe_dispatch ;;
    ""|--once) dispatch_and_wait ;;
    *)
        echo "usage: run_cron.sh [--watch | --once-if-idle]" >&2
        exit 2
        ;;
esac
