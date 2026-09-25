"""A device_tracker per person, in Home Assistant's own currency.

The person's Sextant sensors say where they are in words (a room, a spot, a
zone). This says it the way HA's person entity, the Map card and every zone
automation already understand: ``home`` while Sextant hears any of the
person's things - BLE is far surer of "in the house" than GPS is at the
property line - and, once it has lost them, the coordinates of the first GPS
tracker that is neither broken nor stale (persons.tracker_fix).
"""
import logging

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

from .persons import owners
from .storage import get_layout

_LOGGER = logging.getLogger(__name__)

UNIQUE_PREFIX = "sextant_person_tracker_"


class SextantPersonTracker(TrackerEntity):
    """Where one person is, as home / a zone / coordinates."""

    _attr_should_poll = False

    def __init__(self, name, slug):
        self._slug = slug
        self._attr_name = f"{name} Sextant"
        self._attr_unique_id = f"{UNIQUE_PREFIX}{slug}"
        self.entity_id = f"device_tracker.{slug}_sextant"
        self._fix = {"location_name": "not_home", "source_type": "gps", "source": "none", "presence": "away"}
        self._attr_device_info = DeviceInfo(
            identifiers={("sextant", f"person_{slug}")},
            name=name, manufacturer="Sextant", model="Sextant (BLE Positioning)",
        )

    @callback
    def set_fix(self, fix):
        """Take the latest fusion (persons.tracker_fix) and publish it."""
        if fix == self._fix:
            return
        self._fix = dict(fix)
        if getattr(self, "hass", None) is not None:
            self.async_write_ha_state()

    @property
    def source_type(self):
        return SourceType.GPS if self._fix.get("source_type") == "gps" else SourceType.BLUETOOTH_LE

    @property
    def location_name(self):
        return self._fix.get("location_name")

    @property
    def latitude(self):
        return self._fix.get("latitude")

    @property
    def longitude(self):
        return self._fix.get("longitude")

    @property
    def location_accuracy(self):
        acc = self._fix.get("accuracy")
        return int(acc) if isinstance(acc, (int, float)) else 0

    @property
    def extra_state_attributes(self):
        return {k: self._fix.get(k) for k in ("source", "presence", "tracker")}


@callback
def ensure_person_trackers(hass, people):
    """Create the tracker of any owner who has none yet."""
    cache = hass.data.get("sextant_trackers")
    add_entities = hass.data.get("sextant_tracker_add")
    if cache is None or add_entities is None:
        return
    new = []
    for person in people:
        slug = person.split(".", 1)[1]
        if slug in cache:
            continue
        state = hass.states.get(person)
        name = (state.attributes.get("friendly_name") if state else None) or slug
        cache[slug] = SextantPersonTracker(name, slug)
        new.append(cache[slug])
    if new:
        _LOGGER.info("Creating Sextant device trackers for %d person(s)", len(new))
        add_entities(new, update_before_add=False)


@callback
def prune_person_trackers(hass, people):
    """Remove the tracker of anyone who no longer owns a thing."""
    keep = {p.split(".", 1)[1] for p in people}
    cache = hass.data.get("sextant_trackers") or {}
    ent_reg = er.async_get(hass)
    for entry in list(ent_reg.entities.values()):
        if entry.platform != "sextant" or not isinstance(entry.unique_id, str) or not entry.unique_id.startswith(UNIQUE_PREFIX):
            continue
        slug = entry.unique_id[len(UNIQUE_PREFIX):]
        if slug not in keep:
            cache.pop(slug, None)
            ent_reg.async_remove(entry.entity_id)


async def async_setup_entry(hass, config_entry, async_add_entities):
    hass.data.setdefault("sextant_trackers", {})
    hass.data["sextant_tracker_add"] = async_add_entities
    layout = get_layout(hass)
    people = list(owners(layout if isinstance(layout, dict) else {}))
    prune_person_trackers(hass, people)
    ensure_person_trackers(hass, people)
    return True
