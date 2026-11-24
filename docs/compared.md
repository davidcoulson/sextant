[Sextant](../README.md) › Where Sextant fits

# Where Sextant fits

Sextant is the fourth step in a lineage:

1. **[Bermuda](https://github.com/agittins/bermuda)** by [@agittins](https://github.com/agittins)
   reads Bluetooth advertisements through ESPHome and Shelly proxies and
   estimates a distance from every proxy to every device. It publishes a
   nearest *area* per device. It has no floor plan.
2. **[BPS](https://github.com/Hogster/BPS)** by [@Hogster](https://github.com/Hogster)
   put those distances on a floor plan: place the proxies, draw rectangular
   zones, trilaterate, and publish a zone and a floor sensor per device.
3. **[BPS-improved](https://github.com/maxi1134/BPS-improved)** by
   [@maxi1134](https://github.com/maxi1134) added polygon zones, sub-zones,
   proxy auto-calibration, Kalman smoothing, position history, floor
   election by hypothesis competition, no-go zones and a dark panel. BPS
   0.2.0 merged that work upstream, and BPS 0.3.0 (a beta in November
   2026) adds people, a people count per zone, music that follows a
   person and suggestions that learn from the answers.
4. **Sextant** grew out of BPS-improved and rebuilt the positioning and the
   panel. It is a new integration domain (`sextant`) with its own sensors
   and its own panel, developed against
   [a Bermuda fork](https://github.com/davidcoulson/bermuda) that exposes
   the APIs the extra features need.

### Next to other room-presence projects

Sextant sits alongside other Home Assistant room-presence projects. Some
do the Bluetooth part, some do the room-occupancy part. Sextant does both,
on a floor plan.

| | Sextant | [BPS](https://github.com/Hogster/BPS) | [Bermuda](https://github.com/agittins/bermuda) | [ESPresense](https://espresense.com) | [Magic Areas](https://github.com/jseidl/hass-magic_areas) | [Area Occupancy Detection](https://github.com/Hankanman/Area-Occupancy-Detection) |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| Tracks phones, watches and tags over Bluetooth | ✅ with Bermuda | ✅ with Bermuda | ✅ | ✅ | 🟡 reads other trackers | ❌ |
| Shows them on your floor plan | ✅ | ✅ | ❌ | ✅ with its Companion app | ❌ | ❌ |
| Knows which room each person or thing is in | ✅ | ✅ | ✅ | ✅ | 🟡 from other trackers | ❌ |
| Knows which floor | ✅ | ✅ | ❌ | ✅ with its Companion app | 🟡 groups rooms by floor | ❌ |
| Spots inside a room (sofa, bed) | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Room sensor that says *who* is inside | ✅ | 🟡 a count per room, in the 0.3 beta | ❌ | ❌ | ❌ | ❌ |
| Combines motion, mmWave, doors and TVs per room | ✅ | 🟡 presence sensors and camera counts, in the 0.3 beta | ❌ | ❌ | ✅ | ✅ |
| Set up by drawing your house in Home Assistant | ✅ | ✅ | ❌ | 🟡 separate web app | ❌ | ❌ |
| Switches lights, heating and media itself | ❌ on purpose¹ | 🟡 lights and music after asking, in the 0.3 beta | ❌ | 🟡 a relay on the node | ✅ | ❌ |
| Room occupancy as a learned percentage | ❌ on purpose² | ❌ | ❌ | ❌ | ❌ | ✅ |
| Live tracking without Home Assistant | ❌ on purpose³ | ❌ | ❌ | ✅ over MQTT | ❌ | ❌ |

✅ yes · 🟡 partly · ❌ no. Based on each project's own README in November
2026, and for BPS on the release notes of its 0.3.0 beta as well.

Left out on purpose:

1. Sextant says who is in each room and leaves what to do about it to
   your automations, or to Magic Areas.
2. A room is on or off, with the people, pets and sensors that put it
   there, so you can see why. Area Occupancy Detection's learned
   percentage suits people who would rather tune a threshold.
3. Sextant is built on Home Assistant's own Bluetooth stack and Bermuda,
   and its sensors, panel and services live there.

**Use them together.** Sextant needs [Bermuda](https://github.com/agittins/bermuda)
to hear the Bluetooth devices. Its room sensors can feed Magic Areas or
Area Occupancy Detection if you like their lighting and climate
automations. Sextant began as a fork of BPS and can
[take over a BPS setup](install.md#upgrading-from-bps-or-bps-improved).
The rest of this page goes into the details.

### Capabilities at a glance

| | Bermuda | BPS | BPS-improved | Sextant |
|---|---|---|---|---|
| Distance per proxy, nearest area | yes | via Bermuda | via Bermuda | via Bermuda |
| Position on a floor plan | no | trilateration | trilateration, bounded to the floor | trilateration fused with proxy fingerprints |
| Rooms | HA areas | rectangles | polygons, adjuster | polygons, adjuster, undo, locks |
| Spots inside a room | no | no | point-in-polygon | elected by probability with dwell |
| Floor | no | nearest proxy | competition between floors | competition, k-nearest proximity, per-floor bias |
| Room stability | n/a | none | none | margin, dwell, stationary lock |
| Near-field anchor | no | no | no | yes |
| Smoothing | per distance | 3-sample average | Kalman | Kalman |
| Proxy calibration | manual rssi offset | no | probes calibrate each other | same, with 3D heights, written into Bermuda if you like |
| Proxy and thing heights | no | no | proxy heights | proxy heights and per-thing carry heights |
| No-go areas | no | no | yes | yes |
| Position history | no | session trail | scrubber, hours to days | scrubber, hours to days |
| Panel | config flow | iframe with a pasted token | dark iframe panel | native Home Assistant panel |
| Manage Bermuda from the panel | n/a | no | no | track, untrack, Find My, Tiles, global options |
| Stability KPI and baselines | no | no | no | yes |
| Live tuning | options flow | no | no | every knob, no restart |
| Units | metres | metres | metres | Home Assistant's unit system |
| Map card | no | yes | with proxy status | same renderer as the panel |
| Updates to clients | polling | polling | polling | websocket push per cycle |
| SciPy | no | required | required | not needed |
| Tiles across address rotation | no | no | no | with the Bermuda fork |

The BPS column is BPS before 0.2.0. From 0.2.0 on it also has what the
BPS-improved column lists.

### BPS 0.3.0 and Sextant

BPS 0.3.0 (a beta in November 2026) goes from placing devices to acting on
where people are. What it adds, and what Sextant has in its place:

| BPS 0.3.0 beta | Sextant |
|---|---|
| Persons: several trackers per person, the best one first | [People](things.md#people): things with an owner, with GPS and Wi-Fi to fall back on |
| A count of known and unknown people per zone | A [room sensor](occupancy.md) that names the people, pets and things in the room, and counts the radar targets in it that no device accounts for (`unknown`) |
| Presence sensors and camera person counts linked to a zone | Radars, presence, motion, door and media sensors and number tests [per room](occupancy.md#every-kind-of-sensor-a-room-can-use) |
| Follow me: music moves with a person, after asking | Not built in. [A recipe](recipes.md#music-follows-a-person) does it with an automation |
| Suggestions that ask before changing lights, and learn from the answers | Not built in. Sextant says who is where and leaves acting on it to your automations |
| Receiver placement from a model of the expected error, weighted by where people spend time | [Advice](advice.md) from the measured error and how well the receivers cover each room, with each room's share of people's time beside it |
| Administrators only by default, with a switch to open it to everyone | Everyone can look and administrators change things: [who can see and change what](install.md#who-can-see-and-change-what) |
| Swedish and English | English |

### What Sextant adds to Bermuda

- A position on the floor plan: trilateration fused with fingerprints the
  proxies build by hearing each other's beacons.
- Rooms as polygons with spots and no-go areas. Room and spot elections
  with a margin, a dwell and a stationary lock, so sensors do not flap.
- Floor election by competition between floors, scaled by proximity and a
  per-floor bias that can vary across the plan (a bias field), for landings
  and double-height rooms where both floors hear a thing equally.
- Alignment anchors that say how the floors stack, with an elevation per
  floor: shared named points on every plan, fitted into one house frame,
  with misplaced pins found and named and each floor's scale audited.
- Proxy calibration with 3D heights, written into Bermuda if you like.
- Location pins: say where a thing really is and Sextant finds the settings
  that fit it, and reports accuracy in metres.
- People: things given an owner place that person, by whichever of them is
  moving or most recently arrived, with a GPS tracker to fall back on when
  the house has lost them.
- mmWave presence sensors (Everything Presence, Apollo R PRO-1 and other
  LD2450 boards) on the plan: a thing near a target is put on it, a still
  target and a still thing make a pin nobody had to tap, and a target no
  device accounts for counts as an untracked person and keeps the room's
  occupancy sensor on.
- Roborock vacuums placed from their own maps, lined up with the plan by
  the rooms both maps name.
- Bermuda management from the panel: track, untrack, Find My accessories,
  Tiles followed across address rotation (with the fork).
- Rooms as sensors: an occupancy binary per room that names the people,
  pets and things in it, ready for an aggregator such as Area Occupancy
  Detection, and a count of the people home. See
  [How occupancy works](occupancy.md).
- Five sensors per thing, a map card, services and a websocket push per
  cycle. Pure numpy, no SciPy.

