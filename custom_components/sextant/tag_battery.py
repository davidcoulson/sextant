"""A tag's battery level, read from the service data in its latest advert.

Home Assistant keeps the last advert (scan response merged in) of every address
a proxy hears, so a tag that says its battery level needs no proxy firmware to
read it. Holy-IoT tags (the cats' collars) send it in a scan response as 0x180A
(Device Information) service data: 0x01, the tag's own MAC, a byte, then the
level; at least one proxy has to scan actively to get it. A standard tag sends
it as byte 0 of 0x180F (Battery Service).
"""

import logging
import time

_LOGGER = logging.getLogger(__name__)
HOLY_IOT = "0000180a-0000-1000-8000-00805f9b34fb"
BATTERY_SERVICE = "0000180f-0000-1000-8000-00805f9b34fb"


def level(service_data, address: str) -> int | None:
    """The battery percentage in a service-data dict, or None when it carries none."""
    service_data = service_data or {}
    data = service_data.get(HOLY_IOT)
    # 0x180A is any device's Device Information: only Holy-IoT's layout, which repeats the MAC, is a level.
    if data is not None and len(data) > 8 and bytes(data[1:7]).hex() == str(address).replace(":", "").lower():
        return min(int(data[8]), 100)   # Holy-IoT tags read over 100 on a fresh cell
    data = service_data.get(BATTERY_SERVICE)
    if data is not None and len(data) >= 1:
        return min(int(data[0]), 100)
    return None


def ibeacon_minors(manufacturer_data) -> dict:
    """{company id (text): minor} for each iBeacon-layout frame in an advert's manufacturer data:
    0x02 0x15, a 16-byte UUID, major, minor, measured power. A Holy-IoT collar sends one per
    slot, all under 0xFFFF; a slot set to Shake or Fall sends its own minor while it fires."""
    out = {}
    for company, data in (manufacturer_data or {}).items():
        data = bytes(data)
        if len(data) == 23 and data[:2] == b"\x02\x15":
            out[str(company)] = int.from_bytes(data[20:22], "big")
    return out


def _last_infos(hass, devices):
    """(slug, address, last advert) for each tracked device ({address: {"slug"}}) with one.

    An address that is not a MAC (an IRK, a FindMy key) simply has no advert."""
    try:
        from homeassistant.components import bluetooth
    except ImportError:
        return
    for address, dev in (devices or {}).items():
        slug = (dev or {}).get("slug")
        if not slug:
            continue
        try:
            info = bluetooth.async_last_service_info(hass, str(address).upper(), False)
        except Exception:  # noqa: BLE001 - bluetooth not set up: nothing to read
            return
        if info is not None:
            yield slug, address, info


def levels_now(hass, devices) -> dict:
    """{slug: level} for each tracked device whose latest advert says one."""
    return {slug: pct for slug, address, info in _last_infos(hass, devices)
            if (pct := level(info.service_data, address)) is not None}


def beacons_now(hass, devices, now_mono=None) -> dict:
    """{slug: {"minors": {company: minor}, "age": s}} for each tracked device whose latest advert
    holds an iBeacon frame. Home Assistant replaces a company's frame with each new advert, so the
    minor is the collar's latest; age is that of its latest packet of any kind (a scan response,
    which carries no frame, renews it too). Read once a cycle, so a Shake or Fall burst shorter
    than a cycle can be missed: give the slot 20 s or more."""
    now_mono = time.monotonic() if now_mono is None else now_mono
    out = {}
    for slug, address, info in _last_infos(hass, devices):
        seen = SEEN.pop(str(address).upper(), set())
        minors = ibeacon_minors(getattr(info, "manufacturer_data", None))
        at = getattr(info, "time", None)
        fresh = not isinstance(at, (int, float)) or now_mono - at <= SEEN_FRESH_S
        if (now := minors.get(str(_COMPANY))) is not None and fresh:
            seen = seen | {now}
        if minors or seen:
            out[slug] = {"minors": minors, "age": round(now_mono - at, 1) if isinstance(at, (int, float)) else None}
            if seen:
                # The 0xFFFF minors the frame log heard change to since the last cycle, and the cached
                # one, so a burst between cycles shows (the cached one may be older than the cycle).
                out[slug]["seen"] = sorted(seen)
    return out


# Diagnostic: a line in config/sextant_collar_log (hourly files, kept 48 h) each time a collar's
# iBeacon minor changes, from a Bluetooth callback, so a Shake or Fall burst shorter than a cycle
# is still seen. The cycle fills COLLARS with Bermuda's devices.
# shortcut: no switch; remove it once the motion slots are understood.
COLLARS: dict = {}   # address (upper case) -> slug
SEEN: dict = {}      # address (upper case) -> minors heard since beacons_now last read it
LOG_DIRNAME = "sextant_collar_log"
LOG_HOURS = 48.0
_COMPANY = 0xFFFF   # Holy-IoT sends its iBeacon frames under 0xFFFF
SEEN_FRESH_S = 30.0  # the cached frame counts as heard this cycle only while its advert is this recent


def watch(devices) -> None:
    """Point the frame log at Bermuda's tracked devices ({address: {"slug"}})."""
    COLLARS.clear()
    COLLARS.update({str(a).upper(): d["slug"] for a, d in (devices or {}).items() if (d or {}).get("slug")})
    for gone in SEEN.keys() - COLLARS.keys():
        del SEEN[gone]


def frame_row(info, last: dict, now: float):
    """The log row for an advert whose iBeacon minor differs from ``last`` (address -> minor),
    updating it; None for anything else. Home Assistant keeps each proxy's last frame, so a
    switch to another proxy can log one stale minor (see ``src``)."""
    address = str(info.address).upper()
    slug = COLLARS.get(address)
    minor = ibeacon_minors({_COMPANY: (info.manufacturer_data or {}).get(_COMPANY) or b""}).get(str(_COMPANY))
    if slug is None or minor is None:
        return None
    SEEN.setdefault(address, set()).add(minor)
    if last.get(address) == minor:
        return None
    row = {"t": round(now, 2), "e": slug, "minor": minor, "was": last.get(address), "src": info.source, "rssi": info.rssi}
    last[address] = minor
    return row


def setup_frame_log(hass):
    """Start the collar frame log; returns the callable that stops it, or None without bluetooth.
    Home Assistant calls back only when an address's data changes, which is when the minor can."""
    try:
        from homeassistant.components import bluetooth
    except ImportError:
        return None
    from . import person_log as person_log_mod  # noqa: PLC0415
    last: dict = {}
    pending: list = []
    timer = [None]

    def flush(*_):
        # One write at a time: rows stay in order and two writers never prune the same file.
        timer[0] = None
        if pending:
            rows, pending[:] = list(pending), []
            hass.async_add_executor_job(person_log_mod.append, hass.config.path(LOG_DIRNAME), rows, LOG_HOURS)

    def seen(info, _change):
        if (row := frame_row(info, last, time.time())) is not None:
            pending.append(row)
            if timer[0] is None:
                timer[0] = hass.loop.call_later(10, flush)

    try:
        unsub = bluetooth.async_register_callback(
            hass, seen, bluetooth.BluetoothCallbackMatcher(manufacturer_id=_COMPANY, connectable=False),
            bluetooth.BluetoothScanningMode.PASSIVE)
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Collar frame log not started: %s", e)
        return None

    def stop():
        unsub()
        if timer[0]:
            timer[0].cancel()
        flush()
    return stop
