"""A tag's battery level from its adverts (sextant.tag_battery) and its sensor."""
import sys
from types import SimpleNamespace as NS

import sextant  # noqa: F401
from sextant import sensor as sensor_mod
from sextant import tag_battery as tb

HOLY = "0000180a-0000-1000-8000-00805f9b34fb"


def test_level_reads_holy_iot_and_the_standard_battery_service():
    # Leela's collar, 2026-11-26: byte 8 is 0x64, 100 %.
    leela = "DA:36:EE:88:7B:DA"
    assert tb.level({HOLY: bytes.fromhex("01da36ee887bda0464")}, leela) == 100
    assert tb.level({HOLY: bytes.fromhex("01da36ee887bda04ff")}, leela) == 100   # capped
    # Device Information that is not Holy-IoT's (no MAC in it) is no level.
    assert tb.level({HOLY: bytes.fromhex("01aabbccddeeff0464")}, leela) is None
    assert tb.level({"0000180f-0000-1000-8000-00805f9b34fb": b"\x2a"}, leela) == 42
    assert tb.level({HOLY: b"\x01\x02"}, leela) is None and tb.level({}, leela) is None and tb.level(None, leela) is None


def test_levels_now_reads_each_tracked_address(monkeypatch):
    import homeassistant.components as comps
    infos = {"DA:36:EE:88:7B:DA": NS(service_data={HOLY: bytes.fromhex("01da36ee887bda0450")}),
             "AA:BB:CC:DD:EE:FF": NS(service_data={})}
    bluetooth = NS(async_last_service_info=lambda h, a, c: infos.get(a))
    monkeypatch.setitem(sys.modules, "homeassistant.components.bluetooth", bluetooth)
    monkeypatch.setattr(comps, "bluetooth", bluetooth, raising=False)
    devices = {"da:36:ee:88:7b:da": {"slug": "leela"}, "aa:bb:cc:dd:ee:ff": {"slug": "phone"},
               "irk:abc": {"slug": "watch"}, "11:22:33:44:55:66": {}}
    assert tb.levels_now(None, devices) == {"leela": 80}
    assert tb.levels_now(None, None) == {}


def test_beacons_now_reads_each_collars_ibeacon_minor(monkeypatch):
    """Leela's collar, 2026-11-28: Slot 1 every 1.1 s, Shake as minor 2, Fall as minor 3."""
    import homeassistant.components as comps
    still = bytes.fromhex("0215decafbadfeedfacef00dda36ee887bdaac652a12c5")
    shake = still[:20] + (2).to_bytes(2, "big") + still[22:]
    assert tb.ibeacon_minors({65535: still}) == {"65535": 0x2A12}
    assert tb.ibeacon_minors({65535: shake, 76: b"\x10\x05"}) == {"65535": 2}   # Apple Nearby is no iBeacon
    assert tb.ibeacon_minors({65535: still[:-1]}) == {} and tb.ibeacon_minors(None) == {}
    fall = still[:20] + (3).to_bytes(2, "big") + still[22:]
    assert tb.ibeacon_minors({"65535": fall}) == {"65535": 3}
    infos = {"DA:36:EE:88:7B:DA": NS(service_data={}, manufacturer_data={65535: shake}, time=98.0),
             "AA:BB:CC:DD:EE:FF": NS(service_data={}, manufacturer_data={76: b"\x10\x05"}, time=99.0)}
    bluetooth = NS(async_last_service_info=lambda h, a, c: infos.get(a))
    monkeypatch.setitem(sys.modules, "homeassistant.components.bluetooth", bluetooth)
    monkeypatch.setattr(comps, "bluetooth", bluetooth, raising=False)
    devices = {"da:36:ee:88:7b:da": {"slug": "leela"}, "aa:bb:cc:dd:ee:ff": {"slug": "phone"}}
    assert tb.beacons_now(None, devices, now_mono=100.0) == {"leela": {"minors": {"65535": 2}, "age": 2.0}}


def test_the_sensor_is_made_once_then_updated(monkeypatch):
    added, written = [], []
    hass = NS(data={"sextant_sensors": {}, "sextant_add_entities": added.extend})
    monkeypatch.setattr(sensor_mod, "find_bermuda_via_device", lambda h, t: None)
    import sextant as pkg
    monkeypatch.setattr(pkg, "update_sextant_sensor_state", lambda h, eid, state: written.append((eid, state)))
    sensor_mod.publish_tag_batteries(hass, {"leela": 90})
    (s,) = added
    assert s.entity_id == "sensor.leela_sextant_battery" and s.native_value == 90 and s._updated
    assert sensor_mod.thing_of_unique_id(s.unique_id) == "leela"
    sensor_mod.publish_tag_batteries(hass, {"leela": 85})
    assert len(added) == 1 and written == [("sensor.leela_sextant_battery", 85)]
    s._state = "unknown"
    assert s.native_value is None
