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


def levels_now(hass, devices) -> dict:
    """{slug: level} for each tracked device ({address: {"slug"}}) whose latest advert says one.

    An address that is not a MAC (an IRK, a FindMy key) simply has no advert."""
    try:
        from homeassistant.components import bluetooth
    except ImportError:
        return {}
    out = {}
    for address, dev in (devices or {}).items():
        slug = (dev or {}).get("slug")
        if not slug:
            continue
        try:
            info = bluetooth.async_last_service_info(hass, str(address).upper(), False)
        except Exception:  # noqa: BLE001 - bluetooth not set up: nothing to read
            return out
        if info is not None and (pct := level(info.service_data, address)) is not None:
            out[slug] = pct
    return out
