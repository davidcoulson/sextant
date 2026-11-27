"""Expose Sextant's occupancy entities to Assist (voice) once, when they are created."""
import logging

_LOGGER = logging.getLogger(__name__)


def expose(hass, entity_id):
    """Expose ``entity_id`` to the conversation agent unless it already has a
    setting: a user who un-exposes one is never overruled."""
    try:
        from homeassistant.components.homeassistant import exposed_entities as ex  # noqa: PLC0415
        if "conversation" not in ex.async_get_entity_settings(hass, entity_id):
            ex.async_expose_entity(hass, "conversation", entity_id, True)
    except Exception as e:  # noqa: BLE001 - voice is a convenience, never a stop
        _LOGGER.debug("Not exposed to Assist: %s: %s", entity_id, e)
