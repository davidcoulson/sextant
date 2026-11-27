"""One occupancy binary sensor per room (rooms.py).

``binary_sensor.<room>_sextant_occupancy`` is ``on`` while Sextant places any
tracked thing in the room; its attributes name the people, pets and things.
Each sensor sits on its own ``<Room>`` device, which is put in the
room's linked Home Assistant area when the device is first created (and
left alone after that, so moving it in HA sticks).
"""
import logging
from datetime import datetime
import time

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .assist import expose
from .rooms import HOUSE_ID, floor_ids, ids_for, people_aggregate_ids, people_ids, room_keys
from .storage import get_layout

_LOGGER = logging.getLogger(__name__)

UNIQUE_PREFIX = "sextant_room_occupancy_"
PEOPLE_PREFIX = "sextant_room_people_"
RESTORE_GRACE_S = 600.0


class SextantRoomOccupancy(BinarySensorEntity, RestoreEntity):
    """Whether anyone Sextant tracks is in one room, and who."""

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    icons = ("mdi:map-marker-radius", "mdi:map-marker-radius-outline")      # on, off: anyone, pets included

    @property
    def icon(self):
        return self.icons[0 if self._attr_is_on else 1] if self.icons else None

    def __init__(self, key, ids):
        self.key = key                      # (floor, room)
        self._attr_name = ids["name"]
        self._attr_unique_id = ids["unique_id"]
        self.entity_id = ids["entity_id"]
        self._attr_is_on = False
        self.memory = None                  # rooms.settle's state between readings
        self._attr_extra_state_attributes = {"room": key[1], "floor": key[0], "count": 0, "people": [], "pets": [], "things": []}
        self._attr_device_info = DeviceInfo(
            identifiers={("sextant", f"room_{ids['unique_id'][len(UNIQUE_PREFIX):]}")},
            name=key[1], manufacturer="Sextant", model="Room",
        )

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        expose(self.hass, self.entity_id)
        # A restart finds nothing placed yet: a room that was on stays on for RESTORE_GRACE_S unless the cycle says it is occupied (carried over, not cleared).
        last = await self.async_get_last_state()
        # One deadline per Home Assistant process: a reload or rename must not grant a fresh grace.
        until = self.hass.data.setdefault("sextant_restore_deadline", time.time() + RESTORE_GRACE_S)
        if last is not None and last.state in ("on", "off"):
            # "Occupied since 07:40" must not become "since the restart" (__init__._carry_since).
            try:
                self.restored_since = (datetime.fromisoformat(last.attributes.get("since")).timestamp(), last.state == "on")
            except (TypeError, ValueError, OverflowError):
                pass
        if last is not None and last.state == "on" and time.time() < until:
            self._attr_is_on = True
            self._attr_extra_state_attributes = {**self._attr_extra_state_attributes, "sources": ["restored"],
                                                 **{k: last.attributes[k] for k in ("since", "state") if k in last.attributes}}
            self.restore_until = until
            self.restored_door_hold = bool(last.attributes.get("door_hold"))   # a sleeper's door hold outlives the restart
            at, who = last.attributes.get("door_at"), last.attributes.get("door_people")
            self.restored_door_at = float(at) if isinstance(at, (int, float)) and not isinstance(at, bool) and at == at and abs(at) != float("inf") else None
            if isinstance(who, list):
                self.door_people = [w for w in who if isinstance(w, str)]
            self.async_write_ha_state()

    def set_occupancy(self, is_on, attrs):
        """Push one cycle's answer; written only when something changed."""
        if is_on == self._attr_is_on and attrs == self._attr_extra_state_attributes:
            return
        self._attr_is_on = is_on
        self._attr_extra_state_attributes = attrs
        if getattr(self, "hass", None) is not None:
            self.async_write_ha_state()


class SextantRoomPeople(SextantRoomOccupancy):
    """The room's sensor for people: on when anyone but a pet's tag is there (lights, not the cats' say). It shares the room's device."""

    icons = ("mdi:account", "mdi:account-outline")

    def __init__(self, key, ids, room_ids):
        super().__init__(key, room_ids)
        self._attr_name = ids["name"]
        self._attr_unique_id = ids["unique_id"]
        self.entity_id = ids["entity_id"]


class SextantAggregateOccupancy(SextantRoomOccupancy):
    """Whether anyone is on one floor, or in the house, and who: the rooms' answers summed up."""

    icons = None

    def __init__(self, key, ids, device_name):
        self.key = key
        self._attr_name = ids["name"]
        self._attr_unique_id = ids["unique_id"]
        self.entity_id = ids["entity_id"]
        self._attr_is_on = False
        self._attr_extra_state_attributes = {"rooms": [], "people": [], "pets": [], "count": 0}
        self._attr_device_info = DeviceInfo(identifiers={("sextant", ids.get("device_id", ids["unique_id"]))}, name=device_name,
                                            manufacturer="Sextant", model="Occupancy")

    async def async_added_to_hass(self):
        expose(self.hass, self.entity_id)     # computed from the rooms each publish: nothing to restore


@callback
def ensure_aggregate_sensors(hass, layout):
    """A sensor per floor and one for the house, created once, dropped with the floor."""
    cache = hass.data.get("sextant_aggregate_sensors")
    add_entities = hass.data.get("sextant_room_add")
    if cache is None or add_entities is None:
        return
    wanted = {("house", None): (HOUSE_ID, "House"), ("house_people", None): (people_aggregate_ids(HOUSE_ID), "House")}
    for floor, ids in floor_ids(room_keys(layout)).items():
        wanted[("floor", floor)] = (ids, floor)
        wanted[("floor_people", floor)] = (people_aggregate_ids(ids), floor)
    new = []
    for key, (ids, device) in wanted.items():
        if key not in cache:
            cache[key] = SextantAggregateOccupancy(key, ids, device)
            new.append(cache[key])
    for key in [k for k in cache if k not in wanted]:
        del cache[key]
    ent_reg = er.async_get(hass)
    uids = {ids["unique_id"] for ids, _d in wanted.values()}
    for entry in list(ent_reg.entities.values()):
        if (entry.platform == "sextant" and entry.domain == "binary_sensor" and isinstance(entry.unique_id, str)
                and entry.unique_id not in uids and entry.unique_id.startswith(("sextant_floor_occupancy_", "sextant_house_occupancy", "sextant_floor_people_occupancy_", "sextant_house_people_occupancy"))):
            ent_reg.async_remove(entry.entity_id)
    if new:
        add_entities(new, update_before_add=False)


def _follow_ids(ent_reg, sensor, ids):
    """A room that gained a namesake on another floor now shows its floor in the
    entity id (and the other way round). The registry entry follows, unless the
    new id is taken; Home Assistant re-adds the entity under the new id by itself."""
    if sensor.entity_id == ids["entity_id"] and sensor._attr_unique_id == ids["unique_id"]:
        return
    changes = {}
    if sensor.entity_id != ids["entity_id"]:
        if ent_reg.async_get(ids["entity_id"]) is not None:
            ids = {**ids, "entity_id": sensor.entity_id}     # taken: keep ours, or we would write another entity's state
        else:
            changes["new_entity_id"] = ids["entity_id"]
    if sensor._attr_unique_id != ids["unique_id"]:
        changes["new_unique_id"] = ids["unique_id"]
    if changes and ent_reg.async_get(sensor.entity_id) is not None:
        ent_reg.async_update_entity(sensor.entity_id, **changes)
    sensor.entity_id = ids["entity_id"]
    sensor._attr_unique_id = ids["unique_id"]
    sensor._attr_name = ids["name"]


@callback
def ensure_room_sensors(hass, layout):
    """Create the sensors (anyone, and people only) of any room on the plan that has none yet."""
    cache = hass.data.get("sextant_room_sensors")
    add_entities = hass.data.get("sextant_room_add")
    if cache is None or add_entities is None:
        return
    people = hass.data.setdefault("sextant_room_people", {})
    new = []
    ent_reg = er.async_get(hass)
    for key, ids in ids_for(room_keys(layout)).items():
        if cache.get(key) is not None:
            _follow_ids(ent_reg, cache[key], ids)
        else:
            cache[key] = SextantRoomOccupancy(key, ids)
            new.append(cache[key])
        pids = people_ids(ids)
        if people.get(key) is not None:
            _follow_ids(ent_reg, people[key], pids)
        else:
            people[key] = SextantRoomPeople(key, pids, ids)
            new.append(people[key])
    if new:
        _LOGGER.info("Creating Sextant occupancy sensors for %d room sensor(s)", len(new))
        add_entities(new, update_before_add=False)
        # The area link needs the device, which exists once the add has run.
        hass.data.setdefault("sextant_room_unlinked", set()).update(s.key for s in new if not isinstance(s, SextantRoomPeople))


@callback
def prune_room_sensors(hass, layout):
    """Remove the sensors of any room no longer on the plan (renamed rooms too)."""
    keep = set(ids_for(room_keys(layout)))
    cache = hass.data.get("sextant_room_sensors") or {}
    people = hass.data.get("sextant_room_people") or {}
    keep_uids = {s._attr_unique_id for k, s in cache.items() if k in keep} | {s._attr_unique_id for k, s in people.items() if k in keep}
    for i in ids_for(room_keys(layout)).values():
        keep_uids |= {i["unique_id"], people_ids(i)["unique_id"]}
    for key in [k for k in cache if k not in keep]:
        del cache[key]
    for key in [k for k in people if k not in keep]:
        del people[key]
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    for entry in list(ent_reg.entities.values()):
        if entry.platform != "sextant" or not entry.entity_id.startswith("binary_sensor.") or not isinstance(entry.unique_id, str) or not entry.unique_id.startswith((UNIQUE_PREFIX, PEOPLE_PREFIX)):
            continue
        if entry.unique_id in keep_uids:
            continue
        device_id = entry.device_id
        ent_reg.async_remove(entry.entity_id)
        if device_id and not any(e.device_id == device_id for e in ent_reg.entities.values()):
            dev_reg.async_remove_device(device_id)


@callback
def link_room_areas(hass, layout):
    """Put each new room device in the room's linked HA area, once.

    Runs each cycle for the rooms still waiting; a room whose device is not
    registered yet waits for the next cycle, one with no linked area is done.
    A device the user has since moved is never moved back.
    """
    pending = hass.data.get("sextant_room_unlinked")
    if not pending:
        return
    cache = hass.data.get("sextant_room_sensors") or {}
    areas = {(k["floor"], k["room"]): k["area_id"] for k in room_keys(layout)}
    dev_reg = dr.async_get(hass)
    for key in list(pending):
        sensor = cache.get(key)
        if sensor is None or getattr(sensor, "hass", None) is None:
            if sensor is None:
                pending.discard(key)
            continue
        area_id = areas.get(key)
        if not area_id:
            pending.discard(key)
            continue
        identifier = next(iter(sensor._attr_device_info["identifiers"]))
        device = _device(hass, dev_reg, identifier)
        if device is None:
            continue
        if device.area_id is None:
            dev_reg.async_update_device(device.id, area_id=area_id)
        pending.discard(key)


def _device(hass, dev_reg, identifier):
    by_identifier = getattr(dev_reg, "async_get_device_by_identifier", None)
    entries = getattr(getattr(hass, "config_entries", None), "async_entries", None)
    if by_identifier is not None and entries is not None:
        for entry in entries("sextant"):
            device = by_identifier(identifier, entry.entry_id)
            if device is not None:
                return device
        return None
    return dev_reg.async_get_device(identifiers={identifier})


async def async_setup_entry(hass, config_entry, async_add_entities):
    hass.data.setdefault("sextant_room_sensors", {})
    hass.data.setdefault("sextant_room_people", {})
    hass.data.setdefault("sextant_aggregate_sensors", {})
    hass.data["sextant_room_add"] = async_add_entities
    layout = get_layout(hass)
    layout = layout if isinstance(layout, dict) else {}
    prune_room_sensors(hass, layout)
    ensure_room_sensors(hass, layout)
    ensure_aggregate_sensors(hass, layout)
    return True
