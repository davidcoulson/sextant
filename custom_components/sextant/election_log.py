"""An opt-in record of every floor election, for replaying them later.

Each cycle publishes, per thing, the elected floor, the smoothed odds and each
contending floor's own fix, fit, proximity score and the proxies behind it
(``floor_cands``). The panel shows the current cycle and forgets it; a wrong
floor at five in the morning is gone by the time anyone looks. Until now the
only way to keep the cycles was an external subscriber left running overnight
(tools/floor_capture.py).

With ``election_log_hours`` set on the Tuning page, Sextant keeps them itself:
one JSON line per thing per cycle, in hourly files under
``config/sextant_election_log``, dropped once they are older than the window.
tools/replay_floors.py reads the directory and replays the elections under
other settings. Measured at about 6 MB an hour for twenty things at
fifteen-second cycles (1.2 KB a row, most of it the per-floor candidates),
and several times that in a house with many proxies. An hour's file is
gzipped once the hour is over (about a sixth of the size), so only the hour
in progress is plain text; ``open_text`` reads either.

This module imports nothing from the rest of the package.
"""
import asyncio
import gzip
import logging
import os
import re
import threading
import time

_LOGGER = logging.getLogger(__name__)

LOG_DIRNAME = "sextant_election_log"
# What is kept of a published row: everything the replay needs and nothing the
# panel alone wants (the trilateration circles, the fingerprint telemetry).
KEEP = (
    "ent", "floor", "floors", "floor_cands", "speed", "zone", "zone_raw", "zone_locked", "closed",
    "nearest_zone", "sub_zone", "anchor", "conf", "cords", "raw", "rms_m", "estimator", "updated",
    "beacon",
)
# One writer, compressor or clear at a time: a clear must not race a gzip in flight.
_FILES = threading.Lock()
_NAME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2})Z\.jsonl(\.gz)?$")


def file_for(stamp: float) -> str:
    """The hourly file a cycle at ``stamp`` belongs in, UTC."""
    return time.strftime("%Y-%m-%dT%HZ.jsonl", time.gmtime(stamp))


def hour_of(name: str):
    """The epoch of the hour a log file covers, or ``None`` if it is not one of ours."""
    m = _NAME.match(name)
    if not m:
        return None
    try:
        return _timegm(*(int(g) for g in m.groups()[:4]))
    except (ValueError, OverflowError):
        return None


def _timegm(year, month, day, hour):
    import calendar
    return calendar.timegm((year, month, day, hour, 0, 0, 0, 0, 0))


def expired(names, now: float, hours: float):
    """Which of the directory's files are older than the window.

    A file covers the hour it is named for; it expires once the END of that
    hour is more than ``hours`` ago, so a 24 h window keeps 24 whole hours
    plus the one in progress. Files that are not ours are never named.
    """
    cutoff = now - hours * 3600
    out = []
    for name in names:
        start = hour_of(name)
        if start is not None and start + 3600 < cutoff:
            out.append(name)
    return out


def open_text(path: str):
    """An hour's file for reading, gzipped or not."""
    return gzip.open(path, "rt", encoding="utf-8") if path.endswith(".gz") else open(path, encoding="utf-8")


def iter_rows(dirpath: str, since: float = 0.0):
    """Every logged row from ``since`` on, one at a time (a day is hundreds of
    megabytes: never the whole log in memory). Files in name order."""
    import json
    try:
        names = sorted(os.listdir(dirpath))
    except OSError:
        return
    for name in names:
        hour = hour_of(name)
        if hour is None or hour + 3600.0 < since:
            continue
        if name + ".gz" in names:
            continue   # listed mid-compression: the gzip has the same rows
        path = os.path.join(dirpath, name)
        try:
            fh = open_text(path)
        except FileNotFoundError:
            try:
                fh = open_text(path + ".gz")   # gzipped since the listing
            except OSError:
                continue
        with fh:
            try:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue   # a line cut short by a restart
                    if isinstance(row, dict) and row.get("t", 0) >= since:
                        yield row
            except (OSError, EOFError) as e:
                _LOGGER.debug("Election log %s not read to its end: %s", name, e)


def usage(dirpath: str):
    """(files, bytes) the log holds on disk now."""
    files = size = 0
    try:
        names = os.listdir(dirpath)
    except OSError:
        return 0, 0
    for name in names:
        if hour_of(name) is not None:
            try:
                size += os.path.getsize(os.path.join(dirpath, name))
                files += 1
            except OSError:
                pass
    return files, size


def _archived(path: str) -> bool:
    """The plain file's rows already end its gzip (a stop between the gzip
    landing and the plain file's removal), so appending them would log the hour twice."""
    try:
        with open(path, "rb") as src, gzip.open(path + ".gz", "rb") as gz:
            tail = src.read()
            return gz.read().endswith(tail)
    except (OSError, EOFError):  # a truncated archive: keep the plain rows (appended, as before)
        return False


def compress_closed(dirpath: str, now: float):
    """Gzip every plain file whose hour is over. The plain file goes only
    after its gzip is in place under the final name. Caller holds ``_FILES``."""
    import shutil
    this_hour = now // 3600 * 3600
    for name in os.listdir(dirpath):
        start = hour_of(name)
        if start is None or name.endswith(".gz") or start >= this_hour:
            continue
        path = os.path.join(dirpath, name)
        try:
            if os.path.exists(path + ".gz") and _archived(path):
                pass  # already archived: stopped between the gzip landing and this remove
            elif os.path.exists(path + ".gz"):
                # The clock stepped back into an archived hour: add the late
                # rows as a second gzip member instead of replacing the archive.
                with open(path, "rb") as src, gzip.open(path + ".gz", "ab") as dst:
                    shutil.copyfileobj(src, dst)
            else:
                with open(path, "rb") as src, gzip.open(path + ".gz.tmp", "wb") as dst:
                    shutil.copyfileobj(src, dst)
                os.replace(path + ".gz.tmp", path + ".gz")
            os.remove(path)
        except OSError as e:
            _LOGGER.debug("Election log %s not compressed: %s", name, e)


def slim(row: dict, stamp: float) -> dict:
    """One published row, cut down to what the replay reads."""
    rec = {"t": round(stamp, 3)}
    for key in KEEP:
        if key in row:
            rec[key] = row[key]
    rec["radii_n"] = len(row.get("radii") or [])
    return rec


class ElectionLog:
    """Buffers a cycle's rows and appends them to the hour's file in one write."""

    def __init__(self, dirpath: str):
        self.dirpath = dirpath
        self._buffer = []
        self._pruned_hour = None
        self._emptied = False   # off and already swept: no directory scan per cycle

    def add(self, row: dict, stamp: float | None = None):
        if isinstance(row, dict) and row.get("floor_cands"):
            self._buffer.append(slim(row, time.time() if stamp is None else stamp))

    async def flush(self, hours: float, now: float | None = None):
        """Write what the cycle recorded, and drop files past the window.

        ``hours`` <= 0 means the log is off: the buffer is discarded and the
        files already written are deleted, once (a scan on the first cycle
        after a restart or after switching off, none while it stays off).
        """
        rows, self._buffer = self._buffer, []
        if hours is None:   # the setting could not be read: touch nothing
            return 0
        if hours <= 0:
            if not self._emptied:
                self._emptied = True
                await clear(self.dirpath)
            return 0
        self._emptied = False
        if not rows:
            return 0
        now = time.time() if now is None else now
        try:
            await asyncio.to_thread(self._write, rows, now, hours)
        except Exception as e:  # noqa: BLE001 - a log must never stop the cycle
            _LOGGER.warning("Election log not written: %s", e)
            return 0
        return len(rows)

    def _write(self, rows, now, hours):
        import json
        with _FILES:
            os.makedirs(self.dirpath, exist_ok=True)
            with open(os.path.join(self.dirpath, file_for(now)), "a", encoding="utf-8") as fh:
                for rec in rows:
                    fh.write(json.dumps(rec, separators=(",", ":"), default=str) + "\n")
            hour = int(now // 3600)
            if self._pruned_hour == hour:
                return
            self._pruned_hour = hour
            for name in expired(os.listdir(self.dirpath), now, hours):
                try:
                    os.remove(os.path.join(self.dirpath, name))
                except OSError as e:
                    _LOGGER.debug("Election log %s not removed: %s", name, e)
            compress_closed(self.dirpath, now)


async def clear(dirpath: str):
    """Delete every log file (ours only), returning (files, bytes) removed.

    Turning the log off calls this once; the ``sextant/election_log/clear``
    command calls it too.
    """
    def _locked():
        with _FILES:
            return _clear()

    def _clear():
        files = size = 0
        try:
            names = os.listdir(dirpath)
        except FileNotFoundError:
            return 0, 0
        for name in names:
            if hour_of(name) is None:
                continue
            path = os.path.join(dirpath, name)
            try:
                size += os.path.getsize(path)
                os.remove(path)
                files += 1
            except OSError as e:
                _LOGGER.debug("Election log %s not removed: %s", name, e)
        return files, size
    return await asyncio.to_thread(_locked)


def get(hass) -> ElectionLog:
    """The one log for this hass, under config/sextant_election_log."""
    log = hass.data.get("sextant_election_log")
    if log is None:
        log = hass.data["sextant_election_log"] = ElectionLog(hass.config.path(LOG_DIRNAME))
    return log
