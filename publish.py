"""Ask GitHub to rebuild the published snapshot.

GitHub's cron is best-effort: it drops or delays scheduled runs under load,
and a dropped run leaves the published page showing dead data with nothing
failing loudly. The local server already polls the feed, so while it runs it
can dispatch the Pages workflow on a timer. The workflow still does the build
and the deploy; this module only starts it, and stays out of the way when it
is not asked to run.
"""
import os
import subprocess
import time

WORKFLOW = "deploy.yml"
BRANCH = "main"


def _gh_dispatch(cwd):
    try:
        proc = subprocess.run(
            ["gh", "workflow", "run", WORKFLOW, "--ref", BRANCH],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if proc.returncode == 0:
        return True, (proc.stdout or "").strip()
    return False, (proc.stderr or proc.stdout or "").strip()


class Publisher:
    """Dispatches the Pages workflow at most once per interval.

    A failed dispatch backs off instead of retrying every tick, so a missing
    or unauthenticated gh does not turn into a stream of failed requests.
    """

    def __init__(self, cwd=None, interval=300, backoff=600, runner=None,
                 clock=time.time, log=None):
        self.cwd = cwd or os.getcwd()
        self.interval = interval
        self.backoff = backoff
        self.clock = clock
        self.log = log or (lambda message: print(message, flush=True))
        self.runner = runner or (lambda: _gh_dispatch(self.cwd))
        self.next_attempt = 0.0
        self.sent = 0
        self.failures = 0

    def due(self):
        return self.clock() >= self.next_attempt

    def tick(self):
        """Dispatch when due. Returns True when a dispatch went out."""
        if not self.due():
            return False
        now = self.clock()
        ok, detail = self.runner()
        if ok:
            self.sent += 1
            self.failures = 0
            self.next_attempt = now + self.interval
            self.log(f"[PUBLISH] dispatched {WORKFLOW} ({self.sent} sent this run)")
        else:
            self.failures += 1
            self.next_attempt = now + self.backoff
            self.log(f"[PUBLISH] dispatch failed, next try in {self.backoff}s: {detail}")
        return ok


def from_env(cwd=None, log=None):
    """Build a publisher from PUBLISH_INTERVAL, or None when it is unset.

    The interval is in seconds. A value of 0 or less disables publishing, and
    an unparseable value is treated as disabled rather than as a surprise.
    """
    raw = os.environ.get("PUBLISH_INTERVAL", "").strip()
    if not raw:
        return None
    try:
        interval = int(raw)
    except ValueError:
        (log or print)(f"[PUBLISH] ignoring PUBLISH_INTERVAL={raw!r}: not a number")
        return None
    if interval <= 0:
        return None
    return Publisher(cwd=cwd, interval=interval, log=log)
