"""Diagnostic: every Apple advertisement heard from a watch or phone, in hourly files under
config/sextant_watch_log (kept 48 h), to find out whether a watch says it is
locked (off a wrist). A watch is a ``device_tracker.private_ble_*watch*`` entity;
Private BLE Device puts the address the watch uses now in ``current_address``.
A line is written when a watch's Apple data changes (Home Assistant passes on
only adverts whose data changed, so the 30 s heartbeat rarely fires). A new
address's first advert reaches us before Private BLE Device names it, so when a
watch's ``current_address`` changes its latest advert is fetched and logged.
Apple's manufacturer data is a run of type, length, payload messages; Nearby
Info (type 0x10) starts with a status nibble and an action nibble, then a flags
byte, which ``ni`` lists as [status, action, flags]. The unlocked flag is
believed to be in one of these. Phones (``*phone*``) are logged too, since
2026-11-26, to test whether an iPhone's action nibble follows its use (screen
on 0x07, recent use 0x0B, call 0x0E, idle 0x03, driving 0x0D, per furiousMAC's
continuity notes); on watches it does not.
The flags byte's 0x80 bit is set while the watch is on a wrist and unlocked,
and clear when it is locked: off a wrist, on a table or its charger (tested on
two watches 2026-11-25). ``worn_now`` reads it for persons.pick.
shortcut: the log (setup) has no switch, watches are found by entity name and old
files are pruned only when a line is written; remove the log once the bit has
held for a few days, keeping the parsers and worn_now."""
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


WORN = 0x80


def worn(data: bytes):
    """True when the advert says on a wrist and unlocked, False when locked, None without Nearby Info."""
    ni = nearby_info(data)
    return None if ni is None else bool(ni[2] & WORN)


def worn_now(hass, ent: str, max_age: float):
    """Whether the watch ``device_tracker.<ent>`` is worn and unlocked, from the latest
    advert at the address Private BLE Device says it uses now; None when unknown
    (no such tracker, no advert in max_age seconds, no Nearby Info)."""
    st = hass.states.get(f"device_tracker.{ent}")
    addr = st.attributes.get("current_address") if st else None
    if not addr:
        return None
    try:
        from homeassistant.components import bluetooth
        info = bluetooth.async_last_service_info(hass, str(addr), False)
    except Exception:  # noqa: BLE001 - no bluetooth: the bit is unknown, the old rules decide
        return None
    # info.time is Home Assistant's monotonic clock, as time.monotonic.
    if info is None or not isinstance(getattr(info, "time", None), (int, float)) or time.monotonic() - info.time > max_age:
        return None
    data = (info.manufacturer_data or {}).get(APPLE)
    return None if data is None else worn(bytes(data))


def since(track: dict, worn_by_ent: dict, now: float, before=None) -> dict:
    """{ent: [since, partial]}: when each watch in ``worn_by_ent`` last turned worn or locked.
    ``track`` (ent -> [worn, since, partial, restored]) carries it from cycle to cycle; an
    unknown reading (absent from ``worn_by_ent``) changes nothing. A watch first
    seen since a restart takes the time its owner's sensor last published
    (``before``: that sensor's attributes) when that said the same, and otherwise
    now, marked partial: it was already so before then."""
    before = before or {}
    # Seed from the sensor even for watches not heard this cycle, so a first cycle
    # with no advert yet does not lose what it said before the restart.
    for ent, worn in (before.get("watches") or {}).items():
        old = (before.get("watches_since") or {}).get(ent)
        if ent not in track and isinstance(worn, bool) and isinstance(old, (list, tuple)) and len(old) == 2:
            track[ent] = [worn, old[0], bool(old[1]), True]
    for ent, worn in worn_by_ent.items():
        cur = track.get(ent)
        if cur is not None and cur[0] == worn:
            cur[3] = False   # heard live: a flip from here on is seen when it happens
        else:
            # Not heard live before (none, or only what the sensor said): it may have flipped earlier.
            track[ent] = [worn, now, cur is None or cur[3], False]
    return {ent: track[ent][1:3] for ent in worn_by_ent}


def _logged(eid: str) -> bool:
    return eid.startswith("device_tracker.private_ble_") and ("watch" in eid or "phone" in eid)


def setup(hass):
    """Start logging; returns the callable that stops it, or None without bluetooth."""
    try:
        from homeassistant.components import bluetooth
        from homeassistant.core import callback
    except ImportError:
        return None
    watches = {}          # address (upper case) -> entity_id
    refreshed = [0.0]
    last = {}             # entity_id -> (hex, time written)
    pending = []

    def refresh(now):
        watches.clear()
        for s in hass.states.async_all("device_tracker"):
            if _logged(s.entity_id):
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
        hexed = bytes(data).hex() + "@" + str(info.address).upper()   # a new address is news even with the same data
        prev = last.get(ent)
        if prev and prev[0] == hexed and now - prev[1] < HEARTBEAT:
            return
        last[ent] = (hexed, now)
        pending.append({"t": round(now, 1), "e": ent, "addr": info.address, "src": info.source, "rssi": info.rssi,
                        "apple": bytes(data).hex(), "types": [k for k, _ in messages(bytes(data))], "ni": nearby_info(bytes(data)),
                        "chg": not prev or prev[0] != hexed})
        if len(pending) >= 20:
            flush()
        elif timer[0] is None:
            timer[0] = hass.loop.call_later(15, flush)

    def address_of(state):
        return state.attributes.get("current_address") if state else None

    @callback   # runs for every state change, so cheap checks only
    def is_move(data):
        eid = data.get("entity_id", "")
        return (_logged(eid)
                and bool(address_of(data.get("new_state")))
                and address_of(data.get("new_state")) != address_of(data.get("old_state")))

    @callback   # on the event loop: a plain listener would run in a worker thread
    def moved(event):
        addr = address_of(event.data["new_state"])
        refresh(time.time())
        if (info := bluetooth.async_last_service_info(hass, addr, False)) is not None:
            seen(info, None)

    def stop(*unsubs):
        def _stop():
            for u in unsubs:
                u()
            flush()
        return _stop

    try:
        # connectable=False: every scanner, as Private BLE Device listens.
        return stop(bluetooth.async_register_callback(
            hass, seen, bluetooth.BluetoothCallbackMatcher(manufacturer_id=APPLE, connectable=False),
            bluetooth.BluetoothScanningMode.PASSIVE), hass.bus.async_listen("state_changed", moved, event_filter=is_move))
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Watch advertisement log not started: %s", e)
        return None
