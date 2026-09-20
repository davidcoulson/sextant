[Sextant](../README.md) › Things

# Things

![The Things page: what is tracked, with its class icon, and everything Bermuda hears but does not track, with where the loudest proxy is](../img/screenshots/sextant-things.png)

Bermuda's device management without its options flow. **Add a thing…** asks
what you are adding, because how a thing is followed depends on whether its
Bluetooth address stays put:

| What | What it needs |
|---|---|
| A phone or watch | Its Identity Resolving Key. A phone changes its address every few minutes and only that key follows it. Paste the key here and Sextant fills in Home Assistant's own Private BLE Device form, which will only take a key it can watch resolve an address right now — so keep the phone awake and near a proxy. |
| An AirTag or FindMy tag | Its pairing keys, exported from the Mac it was paired from or from iCloud, depending on the macOS version. Opens the walkthrough on the [Bermuda page](bermuda.md). |
| A Tile | A binding, on the [Bermuda page](bermuda.md), so one Tile is followed across its rotations. |
| Anything else | Nothing. An iBeacon, a fitness band or a tag with a fixed address simply appears below once a couple of proxies hear it. |

The top list is what
is tracked: click the name or the icon to open the thing dialog and set a
display name, a class (person, dog, cat, phone, watch, headphones, keys, tag and more,
each with its icon on the map), pronouns (he, she, they or it: how the panel
refers to it; left unset, a man is he, a woman she, a device it, and a
person, child or pet they), who it belongs to (a Home Assistant person),
a colour used everywhere it is drawn, a
photo framed in a circle that replaces the icon, the height it is carried
at, a reference-power trim, and its own position estimator. **Untrack** removes it from Bermuda and
removes its five Sextant sensors and its device with it; a device untracked
while Home Assistant was down is cleaned up on the next cycle.

Below is everything Bermuda hears but does not track, with the kind of
device (iBeacon, Tile, Apple, IRK, plain address), what it appears to be
(the Bermuda fork names families the Bluetooth SIG's lists cannot — a Govee
sensor, a Samsung SmartTag — and says when that kind rotates its address,
which is why some of them cannot be followed at all), where it is (the room
of the loudest placed proxy) and the signal there in dBm, and for Apple
adverts what they are (AirPods and accessories, an iPhone, Watch or Mac
nearby, a Find My tag). Search by name, address, room, floor, proxy, kind
or maker. Adverts heard only by unplaced proxies are ignored, and the
proxies' own probe beacons are hidden. **Track…** opens the same dialog
first, so you choose the name, class and height before Bermuda is told and
reloads.

## People

Give things an owner - **Belongs to**, a Home Assistant person - and two
things follow. On Live, each owner gets a heading of their own (their
picture, and where they are), which folds their things away with a click. And each owner gets three sensors of their own:
`sensor.<person>_sextant_person_location` (the spot, or the room),
`_sextant_person_room` and `_sextant_person_floor`, with `via` naming the
thing they came from. Automations can then ask where David is rather than
where his phone is.

Which thing speaks for a person: only things that **give their owner's
location** count - by default a watch, a phone, or a person's or pet's own
tag, not headphones, keys, a bag or other tags, which go along only some of
the time (the thing dialog switches it either way); of those, only ones
heard recently and placed in a room. One moving now, or that arrived where
it is in the last ten minutes, beats one that has sat still longer (the
phone left on the couch is not you), and among those a pet's own tag, a
watch, then a phone. When nothing is on the move, the one that arrived
where it is most recently wins - the phone you carried downstairs, not the
watch on its charger since last night.

A thing can also name an **On-charger sensor** - its battery state from
iCloud3, the companion app, or any `binary_sensor` that is on while it
charges. While that reads Charging, Charged or Full, the thing does not
speak for its owner at all: a watch on its charger is on nobody's wrist.
Unavailable or unknown counts as not charging, so a sensor that has nothing
to say never takes a thing out of the running. The location sensor's
`considered` list marks a thing left out this way with `on_charger`.

