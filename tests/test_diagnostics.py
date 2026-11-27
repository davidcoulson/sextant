"""The diagnostics download carries counts and receiver state, never names or geometry."""
import asyncio
import json

import sextant
from sextant import diagnostics, storage as st

from conftest import make_hass


def test_diagnostics_have_counts_and_no_plan_geometry():
    hass = make_hass()
    st._bucket(hass)["layout"] = {"floor": [{"name": "Secret Floor", "zones": [{"name": "Bedroom"}], "receivers": [{"entity_id": "rx"}]}],
                                  "tuning": {"x": 1}}
    hass.data.setdefault("sextant", {})["rl_offline"] = ["rx"]
    out = asyncio.new_event_loop().run_until_complete(diagnostics.async_get_config_entry_diagnostics(hass, None))
    assert out["floors"] == [{"rooms": 1, "receivers": 1}] and out["receivers_offline"] == 1
    assert "rx" not in json.dumps(out) and "Secret Floor" not in json.dumps(out) and "Bedroom" not in json.dumps(out)
