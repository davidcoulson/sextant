[Sextant](../README.md) › Voice and occupancy

# Occupancy and voice

For how a room turns on and off, with worked examples, see
[How occupancy works](occupancy.md).

## What Sextant publishes

| Entity | Meaning |
|---|---|
| `binary_sensor.<room>_sextant_occupancy` | on while anyone is in the room. Attributes: `people`, `pets`, `things`, `count`, `state` (`occupied`, `extended` or `clear`), `since`, `forced`, `hold_over`, `sources` (why it is on: `bluetooth`, `radar`, `media_player`, `sensor`, `forced`, `door`, `restored`, `hold`) |
| `binary_sensor.<room>_sextant_people_occupancy` | the same without pets: a pet's tag alone leaves it off (radars and other sensors still count) |
| `binary_sensor.<floor>_sextant_floor_occupancy` | on while anyone is on the floor; `rooms`, `people`, `pets`, `count` |
| `binary_sensor.sextant_house_occupancy` | on while anyone is in the house; the same attributes across all floors |
| `switch.<room>_sextant_force_occupied` | while on, the room's sensor stays on whatever Sextant hears (a still reader, a sleeper); it survives a restart, and turns itself off after `room_force_max_secs` if that is set (default 0 = never) |
| `sensor.sextant_people_home` | how many people are home; `home` and `away` list them |

A restart forgets a hold in progress (the time since the last reading), but the room keeps its `since`, so a long stay is still "extended" afterwards; a door hold carries over.

Two tuning settings (`sextant.set_tuning`): `room_hold_secs` (default 0) keeps a room on that long after the last reading that put someone there, and `room_extended_secs` (default 600) is how long a stay lasts before `state` reads `extended`. Use `state` in automations to treat a long stay differently from someone passing through.

### Per room: timing, other sensors, a door

Select a room on the Edit page and its **Occupancy sensor** block takes:

- **Clears after** and **Extended after**: this room's own timings, instead of the two settings above.
- **Other sensors that mean someone is here**: entity ids of a motion, presence or occupancy binary sensor, a media player, a person or a tracker. The room stays occupied while any of them is `on`, `playing` or `home`, so a guest with no beacon counts. A number can be tested instead: `sensor.tv_power>20` counts while the reading is above 20 (`>`, `>=`, `<`, `<=`; a TV's power draw, a PC's, a lamp's lux, CO₂). An unavailable or non-numeric reading counts as nothing. The room's `inputs` attribute lists the ones that are on.
- **Keep-only sensors**: the same kind of list, for sensors that keep an occupied room on but never turn an empty one on: a TV that is playing, a PC drawing power (`media_player.den_tv, sensor.pc_power>50`). The room's `sources` reads `keep` while only they hold it, and the clear-after starts when they stop.
- **Dark when**: one entity that says the room is dark, as the sensor's `dark` attribute: an on/off entity, or a light sensor with a test (`sensor.kitchen_illuminance<20`). Blank follows the sun (`sun.sun` below the horizon). An automation can then turn lights on only when `dark` is true.
- **Asleep while on**: an on/off entity (a helper, a bed sensor) that is on while someone sleeps here. The sensor's `asleep` attribute follows it, and **Clears after while asleep** replaces the usual clear-after meanwhile (`room_sleep_hold_secs` on the Tuning page for every room; -1 = as usual). It is for people who are seen nowhere, such as a phone that went flat overnight: once everyone named in the room since it came on (less anyone who walked out while others stayed) is placed in another room, they are up, and the sleep clear-after stops applying (the usual one, or the extended one after a long stay, applies instead). It only keeps a room on: it never brings back a room that has cleared.
- **Mode from**: what the room is being used for, as the sensor's `mode` attribute. A dropdown (`input_select`) gives its selected option ("Movie"); an on/off entity gives the **label** you type ("Guests") while it is on. `mode` is empty while the entity is off, idle or unavailable.
- **Clears after once extended**: a different clear-after for a stay that has become `extended` (`room_extended_hold_secs`; -1 = as usual), so a room someone has settled into is slower to clear than one they walked through.
- **Wizard**: the same fields one group at a time, each with what it is for and the matching sensors from the room's Home Assistant area to click (link the area first).
- **Sensor repairs**: a Repair is raised for a room sensor (an input or a door) that does not exist, that has been unavailable for `sensor_gone_secs` (6 h), or a binary sensor that has read `on` for `sensor_stuck_secs` (24 h), because a stuck one holds its room occupied. Numbers, media players and trackers are not called stuck, and a media player that reads unavailable (a TV switched off) is not called gone, and a door left shut for days is normal. It clears itself when the sensor reads normally; a restart restarts the clocks.
- **Has an outside door**: someone whose things all go quiet while they are in this room (or while their last position was in it, even if Sextant still showed the room before) has gone out through it. After `exit_quiet_secs` (default 120) unheard they read **Outside** instead of being held in the room, until they are heard again or `away_after_secs` makes them away. A phone that dies in the room reads Outside too. Give the room its **Outside door contact** and the doors are asked first: they read Outside only if some outside door (any room's) was open within `exit_door_secs` (default 300) of when they were last heard. Cats never go out this way.
- **Door contact**: a binary sensor (`on` = open) or a cover. Someone who keeps reading in the room for `door_settle_secs` (default 90) after the door closed is taken to have shut themselves in; the room then stays on, however still they are, until the door opens (`door_hold` is true meanwhile) or `door_hold_max_secs` (default 8 h) passes. Someone who shuts the door on the way out stops reading in the room within the wait and is not held. If everyone the hold was for is placed in another room, it lets go. An unavailable contact sensor keeps the hold as it was. A restart keeps it too, with its first start time, so the `door_hold_max_secs` limit is not reset. The inputs are read once a cycle and on each radar reading; a Sextant occupancy sensor or the door itself is ignored if listed as an input. Habits are kept per floor and room name, so renaming a room starts its history again.

## Voice (Assist)

The room, floor and house sensors and the force switches are exposed to Assist the first time they are created, unless you have already set their exposure; un-exposing one is respected. Each room's device is put in the room's Home Assistant area, so area-based sentences work. The force switch is a plain switch: "turn on the kitchen force occupied".

For spoken answers (who is in a room, where someone is, who is home) copy two files:

1. `docs/assist/sextant_sentences.yaml` to `/config/custom_sentences/en/sextant.yaml`
2. the contents of `docs/assist/sextant_intents.yaml` into `configuration.yaml` under `intent_script:`

Restart, then ask: "who is in the kitchen", "is anyone in the office", "where is Alex", "who is home". People must be exposed to Assist for "where is" to hear their name. The sentences are English; add another language by translating the sentence file.
