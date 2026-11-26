"""Diagnostic: every Apple advertisement heard from a watch, in hourly files under
config/sextant_watch_log (kept 48 h), to find out whether a watch says it is
locked (off a wrist). A watch is a ``device_tracker.private_ble_*watch*`` entity;
Private BLE Device puts the address the watch uses now in ``current_address``.
A line is written when a watch's Apple data changes, and every 30 s otherwise.
Apple's manufacturer data is a run of type, length, payload messages; Nearby
Info (type 0x10) starts with a status nibble and an action nibble, then a flags
byte, which ``ni`` lists as [status, action, flags]. The unlocked flag is
believed to be in one of these.
shortcut: watches are found by entity name, the log has no switch and old files
are pruned only when a line is written; remove
this module once the on/off test is read, or move it behind a tuning."""
import logging
import time

from . import person_log as person_log_mod

_LOGGER = logging.getLogger(__name__)
LOG_DIRNAME = "sextant_watch_log"
APPLE = 0x004C
HOURS = 48.0
HEARTBEAT = 30.0


def messages(data: bytes) -> list:
    """[(type, payload bytes)] from Apple manufacturer data; stops at a cut-short message."""
    out, i = [], 0
    while i + 2 <= len(data):
        kind, n = data[i], data[i + 1]
        if i + 2 + n > len(data):
            break
        out.append((kind, data[i + 2:i + 2 + n]))
        i += 2 + n
    return out


def nearby_info(data: bytes):
    """[status, action, flags] from the first Nearby Info message, or None."""
    for kind, p in messages(data):
        if kind == 0x10 and len(p) >= 2:
            return [p[0] >> 4, p[0] & 0x0F, p[1]]
    return None


def setup(hass):
    """Start logging; returns the callable that stops it, or None without bluetooth."""
    try:
        from homeassistant.components import bluetooth
    except ImportError:
        return None
    watches = {}          # address (upper case) -> entity_id
    refreshed = [0.0]
    last = {}             # entity_id -> (hex, time written)
    pending = []

    def refresh(now):
        watches.clear()
        for s in hass.states.async_all("device_tracker"):
            if s.entity_id.startswith("device_tracker.private_ble_") and "watch" in s.entity_id:
                addr = s.attributes.get("current_address")
                if addr:
                    watches[str(addr).upper()] = s.entity_id[len("device_tracker."):]
        refreshed[0] = now

    timer = [None]

    def flush(*_):
        if timer[0]:
            timer[0].cancel()
            timer[0] = None
        if pending:
            rows, pending[:] = list(pending), []
            hass.async_add_executor_job(person_log_mod.append, hass.config.path(LOG_DIRNAME), rows, HOURS)

    def seen(info, _change):
        now = time.time()
        ent = watches.get(str(info.address).upper())
        # A miss may be a watch's new address: look again, at most once a second.
        if ent is None and now - refreshed[0] > 1:
            refresh(now)
            ent = watches.get(str(info.address).upper())
        data = (info.manufacturer_data or {}).get(APPLE)
        if not ent or data is None:
            return
        hexed = bytes(data).hex()
        prev = last.get(ent)
        if prev and prev[0] == hexed and now - prev[1] < HEARTBEAT:
            return
        last[ent] = (hexed, now)
        pending.append({"t": round(now, 1), "e": ent, "addr": info.address, "src": info.source, "rssi": info.rssi,
                        "apple": hexed, "types": [k for k, _ in messages(bytes(data))], "ni": nearby_info(bytes(data)),
                        "chg": not prev or prev[0] != hexed})
        if len(pending) >= 20:
            flush()
        elif timer[0] is None:
            timer[0] = hass.loop.call_later(15, flush)

    def stop(unregister):
        def _stop():
            unregister()
            flush()
        return _stop

    try:
        # connectable=False: every scanner, as Private BLE Device listens.
        return stop(bluetooth.async_register_callback(
            hass, seen, bluetooth.BluetoothCallbackMatcher(manufacturer_id=APPLE, connectable=False),
            bluetooth.BluetoothScanningMode.PASSIVE))
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Watch advertisement log not started: %s", e)
        return None
