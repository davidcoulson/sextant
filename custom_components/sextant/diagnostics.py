"""Download diagnostics: what an issue report needs, with no plan geometry, names or addresses."""
from . import _last_seen, _person_visits, bermuda_source, ws
from .const import DOMAIN
from .storage import get_layout


async def async_get_config_entry_diagnostics(hass, entry):
    layout = get_layout(hass)
    layout = layout if isinstance(layout, dict) else {}
    dom = hass.data.get(DOMAIN) or {}
    floors = [f for f in layout.get("floor") or [] if isinstance(f, dict)]
    scanner_info = bermuda_source.async_get_scanner_directory(hass) or {}
    return {
        "version": ws.RUNNING_VERSION,
        "floors": [{"rooms": len(f.get("zones") or []), "receivers": len(f.get("receivers") or [])} for f in floors],
        "tuning_overrides": dict(layout.get("tuning") or {}),
        "bermuda_features": sorted(bermuda_source.async_features(hass)),
        "scanners_known": len(scanner_info),
        "receivers_offline": len(dom.get("rl_offline") or []),
        "receivers_offline_guessed": len(dom.get("rl_offline_guessed") or []),
        "things_heard": len(_last_seen),
        "people_home": sum(1 for v in _person_visits.values() if isinstance(v, dict) and v.get("arrived") is not None),
        "people_away": sum(1 for v in _person_visits.values() if isinstance(v, dict) and v.get("arrived") is None),
    }
