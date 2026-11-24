"""A record of why each person reads where they do, one JSON line per person
per cycle, in hourly files under config/sextant_person_log, dropped once older
than the ``person_log_hours`` tuning (default 48; 0 = off). Each line carries
the result (source, presence, state, home/away, Wi-Fi word before and after
the confirm hold, GPS zone, seconds since BLE last heard them) and its inputs
(every thing of theirs with its presence, room and age, the thing picked, the
ones ruled out as left behind, each Wi-Fi tracker with its access point and
router last-seen age). ``place`` is the [room, floor] they were put in, null
when they are in no room; the Advice page counts its room use from it
(advice.room_usage). ``chg`` marks a line whose result differs from the last
one, so the changes can be pulled out with a filter. It exists to measure how
often Wi-Fi misleads (Home Assistant's history drops attributes and the
history files hold BLE placements only). About 0.25 MB an hour for each person
at a six-second cycle (a pet tracked as a person is one more).
This module imports nothing from the package."""
import json
import os
import re
import time

LOG_DIRNAME = "sextant_person_log"
_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}Z\.jsonl$")


def row(person, now, source, presence, state, home, wifi_raw, wifi_used, ble_age, gps_zone, ap=None, **inputs):
    """(line, key) for one person's cycle; ``key`` is what a change of result looks like."""
    key = (source, presence, state, bool(home), bool(wifi_raw), bool(wifi_used), gps_zone)
    line = {"t": round(now, 1), "p": person, "src": source, "pres": presence, "state": state, "home": bool(home),
            "wifi": bool(wifi_raw), "wifi_used": bool(wifi_used), "ble_age": None if ble_age is None else round(ble_age),
            "gps": gps_zone, "ap": ap, **inputs}
    return line, key


def append(dirpath, rows, hours, now=None):
    """Append ``rows`` to this hour's file and drop files older than ``hours``.
    Blocking: run it in an executor."""
    now = time.time() if now is None else now
    os.makedirs(dirpath, exist_ok=True)
    with open(os.path.join(dirpath, time.strftime("%Y-%m-%dT%HZ.jsonl", time.gmtime(now))), "a", encoding="utf-8") as f:
        f.write("".join(json.dumps(r, separators=(",", ":"), default=str) + "\n" for r in rows))
    cutoff = time.strftime("%Y-%m-%dT%HZ.jsonl", time.gmtime(now - hours * 3600))
    for n in os.listdir(dirpath):
        if _NAME.match(n) and n < cutoff:
            os.remove(os.path.join(dirpath, n))


def rows(dirpath, since=0.0):
    """Every logged line from ``since`` on, oldest first, one at a time.
    Blocking: run it in an executor."""
    oldest = time.strftime("%Y-%m-%dT%HZ.jsonl", time.gmtime(since))   # an earlier hour's file holds nothing this late
    try:
        names = sorted(n for n in os.listdir(dirpath) if _NAME.match(n) and n >= oldest)
    except OSError:
        return
    for n in names:
        try:
            # errors="replace": bytes a power cut left in the file cost their own line, not the read.
            with open(os.path.join(dirpath, n), encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue   # a line cut short by a restart
                    if isinstance(r, dict) and isinstance(r.get("t"), (int, float)) and r["t"] >= since:
                        yield r
        except OSError:
            continue   # dropped by append() since the listing
