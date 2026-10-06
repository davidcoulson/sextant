DOMAIN = "sextant"

# Global diagnostic sensor: receiver self-localization accuracy (CEP95, m).
# Shared by sensor.py (the entity) and __init__.py (the periodic publisher).
ACCURACY_ENTITY_ID = "sensor.sextant_position_accuracy"
# Global sensor: people the mmWave radars see that no tracked thing accounts for.
UNTRACKED_ENTITY_ID = "sensor.sextant_untracked_people"
# Global sensor: how many people Sextant hears in the house (rooms.people_home).
PEOPLE_HOME_ENTITY_ID = "sensor.sextant_people_home"
# Sextant's own sensors that belong to no thing: never pruned as orphans.
GLOBAL_ENTITY_IDS = frozenset({ACCURACY_ENTITY_ID, UNTRACKED_ENTITY_ID, PEOPLE_HOME_ENTITY_ID})
# The iBeacon UUID every calibration probe advertises (README, "make each probe advertise"), lower-case
# hex without dashes. Bermuda names such a beacon <uuid>_<major>_<minor>; it is never a device to track.
PROBE_BEACON_UUID = "fde3b1502f6443baaee9867f75ee4a6f"
