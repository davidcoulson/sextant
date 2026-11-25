DOMAIN = "sextant"

# Config-entry options (config_flow.py edits them, __init__.py reads them).
OPTION_SHOW_SIDEBAR_PANEL = "show_sidebar_panel"
OPTION_UPDATE_INTERVAL = "update_interval"
# Trilateration (numpy least squares, multi-start) is real CPU work. 1s was
# fine for a handful of things but scales linearly with thing count and
# adds up fast - profiling showed it as the largest chunk of custom-component
# CPU time on a live instance. 15s still updates a thing's room/position
# fast enough for presence automations while cutting recompute volume ~15x.
DEFAULT_UPDATE_INTERVAL = 15

# Global diagnostic sensor: receiver self-localization accuracy (CEP95, m).
# Shared by sensor.py (the entity) and __init__.py (the periodic publisher).
ACCURACY_ENTITY_ID = "sensor.sextant_position_accuracy"
# Global sensor: people the mmWave radars see that no tracked thing accounts for.
UNTRACKED_ENTITY_ID = "sensor.sextant_untracked_people"
# Global sensor: how many people Sextant hears in the house (rooms.people_home).
PEOPLE_HOME_ENTITY_ID = "sensor.sextant_people_home"
# Sextant's own sensors that belong to no thing: never pruned as orphans.
# Global sensor: the one floor everyone at home is on (rooms.household_floor).
HOUSEHOLD_FLOOR_ENTITY_ID = "sensor.sextant_household_floor"
GLOBAL_ENTITY_IDS = frozenset({ACCURACY_ENTITY_ID, UNTRACKED_ENTITY_ID, PEOPLE_HOME_ENTITY_ID, HOUSEHOLD_FLOOR_ENTITY_ID})
# The iBeacon UUID every calibration probe advertises (README, "make each probe advertise"), lower-case
# hex without dashes. Bermuda names such a beacon <uuid>_<major>_<minor>; it is never a device to track.
PROBE_BEACON_UUID = "fde3b1502f6443baaee9867f75ee4a6f"
# What the fit looked like, published on the location sensors so "outside the
# house" can be told from "by a wall". They move with BLE noise every cycle a
# thing is heard, so they are neither recorded (sensor.py) nor on their own a
# reason to write (update_sextant_sensor_state).
# since / spot_since (epoch, kept over a restart) ride along: the Occupancy popup shows how long it has been there.
# settled_conf is conf lifted by that stay (rooms.settled_conf_of); it creeps up every cycle, so it rides here too.
FIT_ATTRIBUTES = ("outside_m", "outside_raw_m", "rms_m", "conf", "n_prox", "nearest_m", "since", "spot_since", "settled_conf")

# No RSSI model reads a thing this close: under it a range is a sentinel (an Android proxy's
# 127 = "no RSSI" relayed as +127 dBm is ~1e-6 m), not a measurement. A raw-input cutoff.
INVALID_RANGE_M = 0.05
