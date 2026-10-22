"""Keep checking Renfe on a short interval and alert as soon as a watched train has seats.

Environment:
  DATE           travel date, DD/MM/YYYY (default 30/10/2026)
  TIMES          comma-separated departure times to watch (default 13:25)
  INTERVAL_SEC   seconds between checks (default 180), randomised by +/- JITTER_SEC (default 40)
  RUN_MINUTES    stop after this long so the next run can take over (default 330)
  STOP_AFTER     ISO time after which monitoring is pointless (default: 30 Oct 13:25 Spain time)
  TEST_NOTIFY    "true" = do one check and send a test notification, then exit
"""
import os
import random
import sys
import time
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

from check_renfe import fetch_trains, launch
from notify import build_alert, send_all

DATE = os.environ.get("DATE", "30/10/2026")
TIMES = [t.strip() for t in os.environ.get("TIMES", "13:25").split(",") if t.strip()]
INTERVAL = int(os.environ.get("INTERVAL_SEC", "180"))
JITTER = int(os.environ.get("JITTER_SEC", "40"))
RUN_SECONDS = int(os.environ.get("RUN_MINUTES", "330")) * 60
STOP_AFTER = datetime.fromisoformat(os.environ.get("STOP_AFTER", "2026-10-30T13:25:00+01:00"))
FAILURES_BEFORE_WARNING = 5


def log(msg):
    print(f"{datetime.now(timezone.utc):%H:%M:%S}Z {msg}", flush=True)


def main():
    test = os.environ.get("TEST_NOTIFY") == "true"
    started = time.monotonic()
    failures, warned = 0, False

    with sync_playwright() as p:
        browser = launch(p)
        while True:
            if datetime.now(timezone.utc) >= STOP_AFTER:
                log("train has departed; stopping")
                return
            try:
                trains = fetch_trains(DATE, browser)
                if not trains:
                    raise RuntimeError("no trains parsed")
                watched = {t["departs"]: t["status"] for t in trains if t["departs"] in TIMES}
                hits = [t for t in TIMES if watched.get(t) == "AVAILABLE"]
                log(f"checked {len(trains)} trains, watched: {watched or 'not listed'}")
                failures = 0
                if warned:
                    send_all("✅ Renfe monitor is working again", f"Checks are succeeding again. Watching {', '.join(TIMES)} on {DATE}.")
                    warned = False
                if hits:
                    log(f"AVAILABLE: {hits} -> alerting")
                    send_all(*build_alert(hits, DATE))
                elif test:
                    send_all(*build_alert([], DATE, ", ".join(TIMES)))
            except Exception as e:
                failures += 1
                log(f"check failed ({failures} in a row): {e}")
                if failures >= FAILURES_BEFORE_WARNING and not warned:
                    send_all(
                        "⚠️ Renfe monitor can't read the Renfe site",
                        f"The last {failures} checks failed (latest error: {str(e)[:200]}). "
                        "Check the site manually until it recovers: https://www.renfe.com/es/es",
                    )
                    warned = True
                try:
                    browser.close()
                except Exception:
                    pass
                browser = launch(p)

            if test:
                return
            if time.monotonic() - started > RUN_SECONDS:
                log("run time limit reached; handing over to next run")
                return
            time.sleep(max(30, INTERVAL + random.uniform(-JITTER, JITTER)))


if __name__ == "__main__":
    sys.exit(main())
