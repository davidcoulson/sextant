"""One "force occupied" switch per room (rooms.py): while on, the room's
occupancy sensor stays on whatever Sextant hears, for a still reader, a
sleeper, or "keep the office on". Voice-controllable like any switch."""
import logging
import time
from datetime import datetime, timezone

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .assist import expose
from .binary_sensor import UNIQUE_PREFIX
from .rooms import ids_for, room_keys, switch_ids
from .storage import get_layout

_LOGGER = logging.getLogger(__name__)
SWITCH_PREFIX = "sextant_room_force_"


class SextantForceOccupied(SwitchEntity, RestoreEntity):
    _attr_should_poll = False

    def __init__(self, key, ids, room_ids):
        self.key = key
        self._attr_name = ids["name"]
        self._attr_unique_id = ids["unique_id"]
        self.entity_id = ids["entity_id"]
        self._attr_is_on = False
        self.on_since = None     # for the auto-off (tuning room_force_max_secs), checked each time the rooms publish
        self._attr_device_info = DeviceInfo(
            identifiers={("sextant", f"room_{room_ids['unique_id'][len(UNIQUE_PREFIX):]}")},
            name=key[1], manufacturer="Sextant", model="Room")

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        self._attr_is_on = last is not None and last.state == "on"
        if self._attr_is_on:      # a restart does not renew the time: the attribute first, last_changed for a switch from before it
            try:
                self.on_since = datetime.fromisoformat(last.attributes["on_since"]).timestamp()
            except (KeyError, TypeError, ValueError):
                self.on_since = last.last_changed.timestamp()
        expose(self.hass, self.entity_id)
        self._changed()

    async def async_turn_on(self, **kwargs):
        self._attr_is_on = True
        self.on_since = time.time()     # turning it on again starts the time again
        self._changed()

    async def async_turn_off(self, **kwargs):
        self._attr_is_on = False
        self._changed()

    @property
    def extra_state_attributes(self):
        on = self._attr_is_on and self.on_since is not None
        return {"on_since": datetime.fromtimestamp(self.on_since, timezone.utc).isoformat(timespec="seconds") if on else None}

    def expire(self):
        """The auto-off: called from inside _publish_rooms, so it writes without publishing again."""
        self._attr_is_on = False
        self.async_write_ha_state()

    def _changed(self):
        if getattr(self, "hass", None) is not None:
            self.async_write_ha_state()
            from . import _publish_rooms  # noqa: PLC0415 - the package imports this platform
            _publish_rooms(self.hass)


@callback
def ensure_room_switches(hass, layout):
    cache, add = hass.data.get("sextant_room_switches"), hass.data.get("sextant_switch_add")
    if cache is None or add is None:
        return
    wanted = {key: (switch_ids(ids), ids) for key, ids in ids_for(room_keys(layout)).items()}
    new = []
    ent_reg = er.async_get(hass)
    for key, (ids, room_ids) in wanted.items():
        have = cache.get(key)
        if have is not None and (have.entity_id != ids["entity_id"] or have._attr_unique_id != ids["unique_id"]):
            # A room gained a namesake: its switch follows the room sensor's new ids (as ensure_room_sensors does).
            changes = {}
            if have.entity_id != ids["entity_id"] and ent_reg.async_get(ids["entity_id"]) is None:
                changes["new_entity_id"] = ids["entity_id"]
            if have._attr_unique_id != ids["unique_id"]:
                changes["new_unique_id"] = ids["unique_id"]
            if changes and ent_reg.async_get(have.entity_id) is not None:
                ent_reg.async_update_entity(have.entity_id, **changes)
            have.entity_id, have._attr_unique_id, have._attr_name = ids["entity_id"], ids["unique_id"], ids["name"]
        if key not in cache:
            cache[key] = SextantForceOccupied(key, ids, room_ids)
            new.append(cache[key])
    for key in [k for k in cache if k not in wanted]:
        del cache[key]
    uids = {ids["unique_id"] for ids, _r in wanted.values()}
    for entry in list(ent_reg.entities.values()):
        if (entry.platform == "sextant" and isinstance(entry.unique_id, str)
                and entry.unique_id.startswith(SWITCH_PREFIX) and entry.unique_id not in uids):
            ent_reg.async_remove(entry.entity_id)
    if new:
        add(new, update_before_add=False)


async def async_setup_entry(hass, config_entry, async_add_entities):
    hass.data.setdefault("sextant_room_switches", {})
    hass.data["sextant_switch_add"] = async_add_entities
    layout = get_layout(hass)
    ensure_room_switches(hass, layout if isinstance(layout, dict) else {})
    return True
