"""A tag's battery level, read from the service data in its latest advert.

Home Assistant keeps the last advert (scan response merged in) of every address
a proxy hears, so a tag that says its battery level needs no proxy firmware to
read it. Holy-IoT tags (the cats' collars) send it in a scan response, as byte 8
of 0x180A (Device Information) service data, so at least one proxy has to scan
actively; a standard tag sends it as byte 0 of 0x180F (Battery Service).
"""

# service UUID -> the byte that holds the level
SERVICES = {
    "0000180a-0000-1000-8000-00805f9b34fb": 8,
    "0000180f-0000-1000-8000-00805f9b34fb": 0,
}


def level(service_data) -> int | None:
    """The battery percentage in a service-data dict, or None when it carries none."""
    for uuid, index in SERVICES.items():
        data = (service_data or {}).get(uuid)
        if data is not None and len(data) > index:
            return min(int(data[index]), 100)   # Holy-IoT tags read over 100 on a fresh cell
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
        if info is not None and (pct := level(info.service_data)) is not None:
            out[slug] = pct
    return out
