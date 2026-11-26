"""Apple manufacturer data split into messages (sextant.watch_adverts)."""
import sextant  # noqa: F401
from sextant import watch_adverts as wa


def test_nearby_info_is_found_among_other_messages():
    data = bytes.fromhex("0c0e" + "11" * 14 + "1005" + "3b1c" + "aabbcc")
    assert [k for k, _ in wa.messages(data)] == [0x0C, 0x10]
    assert wa.nearby_info(data) == [3, 0xB, 0x1C]


def test_cut_short_or_missing_messages_give_nothing():
    assert wa.messages(bytes.fromhex("1005aa")) == []
    assert wa.nearby_info(bytes.fromhex("0c0100")) is None
    assert wa.nearby_info(b"") is None


def test_a_new_address_is_logged_once_private_ble_names_it(monkeypatch):
    """The first advert from a new address arrives before the tracker names it, and identical ones
    are never passed on again, so the address change itself fetches and logs the latest advert."""
    from types import SimpleNamespace as NS
    import sys
    import homeassistant.components as comps
    bluetooth = NS(BluetoothCallbackMatcher=dict, BluetoothScanningMode=NS(PASSIVE="passive"))
    monkeypatch.setitem(sys.modules, "homeassistant.components.bluetooth", bluetooth)
    monkeypatch.setattr(comps, "bluetooth", bluetooth, raising=False)
    adverts, listeners, jobs = [], [], []
    info = NS(address="69:8F:F9:24:7D:BD", source="proxy", rssi=-60,
              manufacturer_data={wa.APPLE: bytes.fromhex("10053b1caabbcc")})
    monkeypatch.setattr(bluetooth, "async_register_callback", lambda h, cb, m, mode: adverts.append(cb) or (lambda: None), raising=False)
    monkeypatch.setattr(bluetooth, "async_last_service_info", lambda h, a, c: info if a == info.address else None, raising=False)
    tracker = NS(entity_id="device_tracker.private_ble_device_david_s_watch", attributes={"current_address": "11:22:33:44:55:66"})
    hass = NS(states=NS(async_all=lambda d: [tracker]), config=NS(path=lambda n: n),
              bus=NS(async_listen=lambda ev, cb: listeners.append(cb) or (lambda: None)),
              loop=NS(call_later=lambda s, cb: NS(cancel=lambda: None)),
              async_add_executor_job=lambda fn, *a: jobs.append(a[1]))
    stop = wa.setup(hass)
    adverts[0](info, None)          # before the tracker knows the address: a miss
    assert not jobs
    old = NS(attributes=dict(tracker.attributes))
    tracker.attributes = {"current_address": info.address}
    listeners[0](NS(data={"entity_id": tracker.entity_id, "old_state": old, "new_state": tracker}))
    stop()
    (row,) = jobs[0]
    assert row["e"] == "private_ble_device_david_s_watch" and row["ni"] == [3, 0xB, 0x1C]
