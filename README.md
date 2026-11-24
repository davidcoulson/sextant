![Sextant](img/logo.png)

# Sextant

**See where everyone and everything is in your house, on your own floor plan, in Home Assistant.**

Sextant uses the Bluetooth proxies you may already have (ESPHome boards,
Shelly switches) to place phones, watches, pet tags and key finders on a
map of your home. It tells your automations which **floor**, which **room**
and even which **spot** in the room (the sofa, the bed, the dog basket)
each one is in, and which rooms have people in them.

[![Open your Home Assistant instance and show Sextant in the Marketplace.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=davidcoulson&repository=sextant&category=Integration)

![The Live page: the floor plan with every tracked thing, the list grouped by person with pets on their own, and the selected dog's card with its room, spot, floor, proxies and timeline](img/screenshots/sextant-live.png)

## What you can do with it

- 🐱 **Find the cat.** Put a tag on her collar and see her on the plan: the
  basement, the guest room, on the bed. The same goes for the dog, your
  phone, your watch or the car keys.
- 💡 **Rooms that know who is in them.** Each room gets an occupancy sensor
  that names the people and pets inside. Lights follow you, the heating
  skips empty bedrooms, and the TV pauses when you walk out.
- 👪 **People, not just phones.** Give each phone, watch or tag an owner and
  Sextant places the person by whichever of their things is with them.
- 🪑 **Steady answers.** Someone asleep on the sofa stays "on the sofa". A
  watch on the line between two rooms doesn't flip back and forth.
- 📡 **Uses what you have.** Add mmWave presence sensors, motion sensors,
  door contacts and TVs to a room and Sextant combines them with
  Bluetooth. Roborock vacuums show up on the plan too (with the
  [Roborock override](https://github.com/davidcoulson/ha-roborock-override)), and with UniFi a
  phone on the home Wi-Fi keeps its owner home.
- 🎯 **Teach it.** If something shows up in the wrong place, click where it
  really is and Sextant works out better settings for your house.
- 🔧 **Set up in an afternoon.** Upload a floor plan, draw your rooms, mark
  where the proxies are and pick what to track. Everything happens on
  Sextant's own page in Home Assistant, with no YAML for Sextant itself.

![A sketch plan of an invented single-floor house with seven rooms. Bluetooth proxies sit in most rooms, motion sensors in the Kitchen, Lounge, Study and Bedroom, a tracking mmWave radar and a presence sensor on the Study wall, a door contact on the Bedroom door, and a TV in the Kitchen whose power draw is used as a sensor. Sam is in the Study, Robin in the Bedroom and Pepper the cat in the Lounge.](docs/images/occupancy-house.svg)

*Bluetooth, mmWave radar, motion sensors, a door and a TV working together:
Sam is in the Study, Robin in the Bedroom and Pepper the cat in the
Lounge. [How occupancy works](docs/occupancy.md) explains it.*

## How it compares

Sextant sits alongside other Home Assistant room-presence projects. Some
do the Bluetooth part, some do the room-occupancy part. Sextant does both,
on a floor plan.

| | Sextant | [BPS](https://github.com/Hogster/BPS) | [Bermuda](https://github.com/agittins/bermuda) | [ESPresense](https://espresense.com) | [Magic Areas](https://github.com/jseidl/hass-magic_areas) | [Area Occupancy Detection](https://github.com/Hankanman/Area-Occupancy-Detection) |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| Tracks phones, watches and tags over Bluetooth | ✅ with Bermuda | ✅ with Bermuda | ✅ | ✅ | ➖ reads other trackers | ❌ |
| Shows them on your floor plan | ✅ | ✅ | ❌ | ✅ with its Companion app | ❌ | ❌ |
| Knows which room each person or thing is in | ✅ | ✅ | ✅ | ✅ | ➖ from other trackers | ❌ |
| Knows which floor | ✅ | ✅ | ❌ | ✅ with its Companion app | ➖ groups rooms by floor | ❌ |
| Spots inside a room (sofa, bed) | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Room sensor that says *who* is inside | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Combines motion, mmWave, doors and TVs per room | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Set up by drawing your house in Home Assistant | ✅ | ✅ | ❌ | ➖ separate web app | ❌ | ❌ |
| Switches lights, heating and media itself | ❌ on purpose¹ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Occupancy as a learned probability | ❌ on purpose² | ❌ | ❌ | ❌ | ❌ | ✅ |
| Runs without Home Assistant | ❌ on purpose³ | ❌ | ❌ | ✅ over MQTT | ❌ | ❌ |

✅ yes · ➖ partly · ❌ no. Based on each project's own README in November
2026.

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
[take over a BPS setup](docs/install.md#upgrading-from-bps-or-bps-improved).
[Where Sextant fits](docs/compared.md) goes into the details.

## What you need

- Home Assistant with [Bermuda](https://github.com/agittins/bermuda)
  installed. For every feature, use
  [the Bermuda fork](https://github.com/davidcoulson/bermuda).
- At least three Bluetooth proxies on each floor: ESP32 boards running
  ESPHome, or Shelly Plus switches and plugs. More proxies give better
  answers.
- A floor plan image for each floor.
- Things to track: phones with the Home Assistant app, watches, iBeacon
  pet tags, Tiles or Find My accessories.

The full list, including the setting each ESPHome proxy needs, is in
[What you need](docs/install.md#what-you-need).

## Quick start

1. In Home Assistant, go to **Settings → Marketplace → Add from link**,
   enter `davidcoulson/sextant` and install **Sextant**. (Adding a project
   from a link asks you to sign in to GitHub once. On Home Assistant
   2026.9 or 2026.10, use HACS → **Custom repositories** instead, add it as
   an Integration, download it and restart.)
2. Go to **Settings → Devices & Services → Add Integration → Sextant**.
3. Open **Sextant** in the sidebar. On **Edit**, add a floor from your plan
   image, set its scale, place the proxies, draw the rooms and save.
4. On **Things**, pick what to track. Positions appear on **Live** a few
   seconds later.

[Getting started](docs/getting-started.md) walks through every step and
ends with a first automation.

## The Sextant page

Sextant adds its own page to the Home Assistant sidebar, in your theme
and units:

- **[Live](docs/live.md)**: everything on the plan, with each thing's room,
  spot, floor and history.
- **Occupancy**: every room at a glance, with who is in it.
- **[Edit](docs/edit.md)**: draw rooms and spots, place proxies and sensors.
- **[Things](docs/things.md)**: choose what to track, give things names,
  colours and owners.
- **Setup**: [Bermuda](docs/bermuda.md), [Proxies](docs/proxies.md),
  [Calibration](docs/calibration.md) and [Advice](docs/advice.md) on where
  one more proxy would help most. Expert mode adds
  [Tuning](docs/tuning.md).

## Docs

| Start | Set up | Improve | Automate |
|---|---|---|---|
| [Getting started](docs/getting-started.md) · [Installing](docs/install.md) · [Hardware](docs/hardware.md) | [Edit](docs/edit.md) · [Things](docs/things.md) · [Bermuda](docs/bermuda.md) · [Proxies](docs/proxies.md) | [Live](docs/live.md) · [Calibration](docs/calibration.md) · [Tuning](docs/tuning.md) · [Advice](docs/advice.md) · [How positioning works](docs/positioning.md) | [Recipes](docs/recipes.md) · [How occupancy works](docs/occupancy.md) · [Sensors, card and services](docs/automation.md) |

Also [Where Sextant fits](docs/compared.md) and
[Data and development](docs/development.md).

## Built with AI, tested in a real house

Sextant was written with [Claude](https://claude.ai) as a coding partner.
Claude wrote most of the code, tests and docs; the author sets the
direction and decides what ships. Every change runs in the author's home
first: more than 100 Bluetooth proxies, 21 rooms on three floors, mmWave
sensors, three robot vacuums, and a mix of people, phones, watches and
seven animals wearing collar tags. Bugs are still bugs, whoever typed
them, so issues and pull requests are welcome.

## Credits

Sextant began as a fork of [Hogster/BPS](https://github.com/Hogster/BPS)
via [maxi1134/BPS-improved](https://github.com/maxi1134/BPS-improved).
Thanks to [@Hogster](https://github.com/Hogster) and
[@maxi1134](https://github.com/maxi1134) for the original integration, to
[@agittins](https://github.com/agittins) for
[Bermuda](https://github.com/agittins/bermuda), and to
[Megarushing](https://github.com/Megarushing/bermuda) for the Find My
support in the Bermuda fork. MIT licensed, see [LICENSE](LICENSE).
