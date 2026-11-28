"""A tag's battery level, read from the service data in its latest advert.

Home Assistant keeps the last advert (scan response merged in) of every address
a proxy hears, so a tag that says its battery level needs no proxy firmware to
read it. Holy-IoT tags (the cats' collars) send it in a scan response as 0x180A
(Device Information) service data: 0x01, the tag's own MAC, a byte, then the
level; at least one proxy has to scan actively to get it. A standard tag sends
it as byte 0 of 0x180F (Battery Service).
"""

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
    import time  # noqa: PLC0415
    now_mono = time.monotonic() if now_mono is None else now_mono
    out = {}
    for slug, _address, info in _last_infos(hass, devices):
        if minors := ibeacon_minors(getattr(info, "manufacturer_data", None)):
            at = getattr(info, "time", None)
            out[slug] = {"minors": minors, "age": round(now_mono - at, 1) if isinstance(at, (int, float)) else None}
    return out
