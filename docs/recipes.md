[Sextant](../README.md) › Recipes: automations and dashboards

# Recipes: automations and dashboards

Copy-paste starting points, each built on the entities in
[Sensors, card, services and API](automation.md). The entity ids are from
one real house; swap in your own.

## Which entity for what

| You want to know | Read | Why this one |
|---|---|---|
| where a **person** is, in words | `sensor.<person>_sextant_person_location` | the finest answer there is: a spot, a room, a GPS zone, or `away` |
| the **room** a person is in, to act on it | `sensor.<person>_sextant_person_room` | stable (hysteresis and the stationary lock), and carries `area_id` |
| whether a person is **home** | `device_tracker.<person>_sextant` | `home` on Sextant's word, the GPS zone once Sextant has lost them; `arrived_at` / `departed_at` say since when |
| where a **thing** is | `sensor.<thing>_sextant_location` (or `_room`, `_floor`, `_spot`) | same shape as the person sensors, one per thing |
| whether a thing is still **heard** | attribute `presence` on any of its sensors | `here` / `quiet` (2–15 min) / `away` |
| where a **robot vacuum** is | `sensor.vacuum_<name>_sextant_room` | placed from the robot's own map, not Bluetooth; `vacuum_state` rides along on `_location` |
| how long since it was heard | attribute `last_heard` on `_location` | an ISO timestamp; see [seconds since](#seconds-since-a-thing-was-heard) |

Trigger on `_room` rather than `_location` when you act on a room: the
location changes every time a thing moves on or off a spot, the room does
not.

## Automations

### When someone left

The person's tracker carries `departed_at` while they are away and
`arrived_at` while they are home, exactly one at a time, and each changes
only when it happens. Trigger on the attribute leaving `None` and the time
is in the event; the departure is the last time any of their things was
heard, not when the 15 minute grace ran out.

```yaml
alias: Alex left
triggers:
  - trigger: state
    entity_id: device_tracker.alex_smith_sextant
    attribute: departed_at
conditions:
  - condition: template
    value_template: "{{ trigger.to_state.attributes.departed_at is not none }}"
actions:
  - action: notify.notify
    data:
      message: >-
        Alex left at
        {{ as_timestamp(trigger.to_state.attributes.departed_at) | timestamp_custom('%H:%M') }}
```

Swap `departed_at` for `arrived_at` for a welcome-home, and for a dashboard:
`home for {{ state_attr('device_tracker.alex_smith_sextant', 'arrived_at') | as_datetime | relative_time }}`.

### Lights follow a person from room to room

The room sensor carries the Home Assistant `area_id` of the room, so the
automation never needs a list of rooms and lights: it lights the area the
person walked into and darkens the one they left.

```yaml
alias: Lights follow Alex
triggers:
  - trigger: state
    entity_id: sensor.alex_smith_sextant_person_room
conditions:
  - condition: template
    value_template: >
      {{ trigger.from_state is not none and trigger.to_state is not none
         and trigger.to_state.attributes.area_id is not none }}
actions:
  - action: light.turn_on
    target:
      area_id: "{{ trigger.to_state.attributes.area_id }}"
  - if:
      - condition: template
        value_template: >
          {{ trigger.from_state.attributes.area_id is not none
             and trigger.from_state.attributes.area_id != trigger.to_state.attributes.area_id }}
    then:
      - action: light.turn_off
        target:
          area_id: "{{ trigger.from_state.attributes.area_id }}"
mode: queued
```

Rooms are linked to areas on the Edit page (a room's **Home Assistant
area**); an unlinked room has `area_id: none` and the condition above skips
it.

### Music follows a person

The same `area_id` finds the speakers. This joins the speaker in the room
the person walked into to the one playing in the room they left.

```yaml
alias: Music follows Alex
triggers:
  - trigger: state
    entity_id: sensor.alex_smith_sextant_person_room
conditions:
  - condition: template
    value_template: "{{ trigger.from_state is not none and trigger.to_state is not none }}"
actions:
  - variables:
      was: "{{ area_entities(trigger.from_state.attributes.area_id or '') | select('match', 'media_player[.]') | list }}"
      now: "{{ area_entities(trigger.to_state.attributes.area_id or '') | select('match', 'media_player[.]') | list }}"
  - condition: template
    value_template: >
      {{ was | count > 0 and now | count > 0 and was[0] != now[0]
         and is_state(was[0], 'playing') }}
  - action: media_player.join
    target:
      entity_id: "{{ was[0] }}"
    data:
      group_members: "{{ [now[0]] }}"
```

It takes the first media player of each area, so give a room with a TV and
a speaker its own choice. Grouping is the speaker system's own:
`media_player.join` works between speakers of one system that supports it
(Sonos, for one).

The room they left keeps playing, which is right when someone else is
still in it. To stop it there, `media_player.unjoin` that speaker once its
room is empty: the helper in the next recipe says when.

### Nobody left in a room

A helper that is on while anyone is in the kitchen, from every person's room
sensor at once. Use it the way you would a motion sensor, without the
"walked in and sat still" problem.

```yaml
template:
  - binary_sensor:
      - name: Kitchen occupied
        state: >
          {{ states.sensor
             | selectattr('entity_id', 'search', '_sextant_person_room$')
             | selectattr('state', 'eq', 'Kitchen')
             | list | count > 0 }}
        delay_off:
          minutes: 2
```

Then `Kitchen occupied` off for 10 minutes → lights off, media off, and so on.

### A cat at the litter boxes

The spot sensor reads the spot's name while the cat is on it. `for` keeps a
cat that walks past from counting.

```yaml
alias: Leela used the litter box
triggers:
  - trigger: state
    entity_id: sensor.leela_sextant_spot
    to: Litter Boxes
    for: "00:00:20"
actions:
  - action: counter.increment
    target:
      entity_id: counter.leela_litter_visits
```

A daily count that stops going up is the earliest sign of a cat that is
unwell; the same trigger with `notify` covers a cat that has not been in a
day.

### Arriving and leaving

The person's device_tracker is `home` while any of their things is heard in
the house, and the GPS zone once Sextant has lost them, so it changes once
per real arrival or departure rather than every time a phone's GPS wanders
across the property line.

```yaml
alias: Sam is home
triggers:
  - trigger: state
    entity_id: device_tracker.sam_smith_sextant
    to: home
actions:
  - action: notify.mobile_app_alex_phone
    data:
      message: Sam is home
```

```yaml
alias: Everyone has left
triggers:
  - trigger: state
    entity_id:
      - device_tracker.alex_smith_sextant
      - device_tracker.sam_smith_sextant
      - device_tracker.robin_smith_sextant
    from: home
conditions:
  - condition: template
    value_template: >
      {{ ['device_tracker.alex_smith_sextant',
          'device_tracker.sam_smith_sextant',
          'device_tracker.robin_smith_sextant']
         | map('states') | select('eq', 'home') | list | count == 0 }}
actions:
  - action: script.house_away
```

### A phone left behind

The person is away by GPS, but the phone is still heard in the house.

```yaml
alias: Alex left his phone
triggers:
  - trigger: state
    entity_id: device_tracker.alex_smith_sextant
    from: home
    for: "00:05:00"
conditions:
  - condition: state
    entity_id: sensor.private_ble_device_alex_phone_sextant_location
    attribute: presence
    state: here
actions:
  - action: notify.mobile_app_sams_iphone
    data:
      message: "Alex's phone is still at home, in the {{ states('sensor.private_ble_device_alex_phone_sextant_room') }}"
```

### A thing that has gone missing

`presence` goes `quiet` two minutes after a thing was last heard and `away`
after fifteen (both tunable). The wallet that was last seen in the Kitchen
at 5:10 PM:

```yaml
alias: Wallet not seen
triggers:
  - trigger: state
    entity_id: sensor.alex_s_wallet_sextant_location
    attribute: presence
    to: away
actions:
  - action: notify.mobile_app_alex_phone
    data:
      message: >
        Wallet not heard since
        {{ as_datetime(state_attr('sensor.alex_s_wallet_sextant_location', 'last_heard')) | as_local | as_timestamp | timestamp_custom('%-I:%M %p') }},
        last in the {{ state_attr('sensor.alex_s_wallet_sextant_location', 'room') }}
```

Watch a tag's battery the same way: a tag that goes `quiet` more and more
often before it goes `away` is a battery on its way out.

### A robot vacuum that has stopped moving

A robot placed on the plan (see [Robot vacuums](things.md#robot-vacuums)) has
the same room sensor as anything else, and its location sensor carries the
vacuum's own state. Stuck under the dining table for twenty minutes:

```yaml
alias: Rocky is stuck
triggers:
  - trigger: state
    entity_id: sensor.vacuum_rocky_sextant_room
    for: "00:20:00"
conditions:
  - condition: state
    entity_id: vacuum.rocky
    state: cleaning
actions:
  - action: notify.mobile_app_alex_phone
    data:
      message: "Rocky has been in the {{ states('sensor.vacuum_rocky_sextant_room') }} for 20 minutes"
```

And one that waits for a room to be empty before cleaning it:

```yaml
alias: Clean the master bedroom once nobody is in it
triggers:
  - trigger: time
    at: "10:00:00"
conditions:
  - condition: template
    value_template: >
      {{ states.sensor | selectattr('entity_id', 'search', '_sextant_person_room$')
         | selectattr('state', 'eq', 'Master Bedroom') | list | count == 0 }}
actions:
  - action: vacuum.start
    target:
      entity_id: vacuum.katniss_everclean_s8
```

### Seconds since a thing was heard

`last_heard` is a timestamp on the location sensor, good to within five
minutes (it is written every five minutes while nothing else about the thing
changes). A number for a dashboard or a condition:

```yaml
template:
  - sensor:
      - name: Socks last heard
        unit_of_measurement: s
        state: >
          {% set t = state_attr('sensor.socks_sextant_location', 'last_heard') %}
          {{ ((now() - as_datetime(t)).total_seconds()) | round(0) if t else none }}
```

## Dashboards

### The floor plan

The map card draws exactly what the Live page draws, on the same live
subscription. One card per floor, or `follow: true` to switch floors with
the first entity listed.

```yaml
type: custom:sextant-map-card
floor: Ground Floor
title: Downstairs
height: 360
trails: true
labels: true
subzones: true
```

```yaml
type: custom:sextant-map-card
follow: true
entities:
  - socks
height: 300
```

### Where everyone is

The where card shows each person and pet with the room, the spot,
how long they have been there, and a ring that fills and colours with how sure
Sextant is (green confident, amber likely, red unsure). The ring reads the
sensor's `settled_conf` when it has one, so a long stay while heard lifts it a
little (it closes at most half the gap to 100%). The badge on the photo
is the device that placed them (phone, watch, collar tag). Tap anyone for the
location sensor's details. Add the resource `/sextant/sextant-where-card.js`
(JavaScript module) first. The card has a visual editor; a person or pet picked
there brings their photo and name.

```yaml
type: custom:sextant-where-card
layout: tiles          # tiles | rooms | strip | rings | pets
columns: 2             # tiles and pets (default 2), rings (default 4)
show_floor: true       # optional: the floor under the room when there is no spot
entities:
  - entity: sensor.alex_smith_sextant_person_location
    person: person.alex_smith      # photo and name
  - entity: sensor.socks_sextant_pet_location
    person: person.socks
rooms:                 # optional, rooms and rings layouts: shows each room's mode
  - binary_sensor.great_room_sextant_occupancy
mode_in_pill: true     # optional, rings: the mode icon in the time pill, not a badge
hide_time: true        # optional, rings: no time under each face (with mode_in_pill, the pill keeps the icon)
```

- `tiles`: a grid of tiles, room as the headline and the spot under it.
  Someone away gets both lines for their town ("Avon, OH"), the badge shows
  driving or walking, the ring is a full grey one (Sextant has no confidence
  to show for someone away: GPS placed them, or nothing did), and the time is how
  long since they left.
- `rooms`: one line per occupied room, avatars stacked (three at most: with more, two and a "+N" that names the rest when hovered), with its mode.
  Anyone away is left out.
- `precise: true` (tiles, rings, strip) shows one line instead: the spot,
  else the room, else the floor, else Home. Someone away keeps their away line.
- `strip`: one wrapping row of chips; pets of one kind on one floor fold
  into one chip ("3 cats · Ground Floor").
- `rings`: people's faces four across with the time there; pets on one line.
  Someone away gets their town without the state, on one line that shrinks
  to fit (hover for the full place); the badge shows driving or walking. With `rooms:` listed, a purple badge under the device badge
  shows the mode of the room they are in (a chef's hat for Cooking, a
  controller for Gaming). `mode_in_pill: true` puts the icon in the time
  pill instead.
- `pets`: the pets only. Each dog gets a card of its own: Inside, Outside
  or Away beside the name, the spot or room and the time there, the collar's address when
  away (pick its `*_current_place_address` sensor as `place`) with the
  distance from home, and a badge for how she was placed (Bluetooth, Wi-Fi,
  GPS). The other pets
  are tiles, two across, with their spot or room and the time there. People listed are not
  drawn; a pet in the same room as one, both placed at least Likely (an amber
  or green ring, a live fix), shows their face on its photo (up to two, overlapping, the right-hand one in
  front) and "with David and Michelle" under it.

The card reads only the entities its config names, so it works on
dashboards served through Strimmer without an override rule.

### A room at a glance

Three ways to show who is in a room and what it is doing, for a room's own
dashboard view. Each takes the room's occupancy sensor; copy the block and
change every `binary_sensor.kitchen_sextant_occupancy` in it (the chips name
it three times) to the room's own.

The chip: faces of who is in the room, how long it has been on, and the
mode's icon. An empty room shows how long it has been empty and who was in
it last (from the recorder). Add the resource `/sextant/sextant-room-chip.js`
(JavaScript module) once. The chip has a visual editor.

```yaml
type: custom:sextant-room-chip
entity: binary_sensor.kitchen_sextant_occupancy
max: 3          # faces before "+N"
```

Mushroom chips for a view's chip row: who is in the room ("2 people · 1
cat"), then the mode and how long ("Cooking · on for 12m", or "Empty since
2:14 PM").

```yaml
type: custom:mushroom-chips-card
chips:
  - type: conditional
    conditions:
      - entity: binary_sensor.kitchen_sextant_occupancy
        state: "on"
    chip:
      type: template
      entity: binary_sensor.kitchen_sextant_occupancy
      icon: mdi:account-multiple
      icon_color: green
      tap_action:
        action: more-info
      content: >
        {%- set a = states[entity].attributes if states[entity] else {} -%}
        {%- set p = a.get('people', []) | count -%}
        {%- set ns = namespace(k={}, out=([p ~ (' person' if p == 1 else ' people')] if p else [])) -%}
        {%- for n in a.get('pets', []) -%}
          {%- set c = state_attr('sensor.' ~ (n | slugify) ~ '_sextant_pet_location', 'via_class') or 'pet' -%}
          {%- set ns.k = dict(ns.k, **{c: ns.k.get(c, 0) + 1}) -%}
        {%- endfor -%}
        {%- for c, n in ns.k.items() -%}{%- set ns.out = ns.out + [n ~ ' ' ~ c ~ ('' if n == 1 else 's')] -%}{%- endfor -%}
        {{ ns.out | join(' · ') or 'On' }}
  - type: template
    entity: binary_sensor.kitchen_sextant_occupancy
    tap_action:
      action: more-info
    icon: >
      {%- set ns = namespace(i='') -%}
      {%- for w in (state_attr(entity, 'mode') or '') | lower | regex_findall('[a-z0-9]+') if not ns.i -%}
        {%- for re, ic in [['^(movie|film|cinema|theat)', 'mdi:movie-open'], ['^(tv|watch)', 'mdi:television-play'], ['^gam', 'mdi:controller'], ['^(music|party|listen)', 'mdi:music'], ['^(sleep|night|bed)', 'mdi:sleep'], ['^read', 'mdi:book-open-variant'], ['^(work|meeting|call|office)', 'mdi:briefcase'], ['^(cook|dinner|meal|bak)', 'mdi:silverware-fork-knife'], ['^(away|vacation)', 'mdi:airplane'], ['^guest', 'mdi:account-multiple']] if not ns.i and w is match(re) -%}
          {%- set ns.i = ic -%}
        {%- endfor -%}
      {%- endfor -%}
      {{ ns.i or ('mdi:tag' if state_attr(entity, 'mode') else ('mdi:clock-outline' if is_state(entity, 'on') else 'mdi:account-off-outline')) }}
    icon_color: >
      {{ 'amber' if state_attr(entity, 'mode') else ('green' if is_state(entity, 'on') else 'disabled') }}
    content: >
      {%- set mode = state_attr(entity, 'mode') -%}
      {%- set s = as_datetime(state_attr(entity, 'since'), default=none) -%}
      {%- set m = ((now() - s).total_seconds() // 60) | int if s else 0 -%}
      {%- set d = (m // 60) ~ 'h ' ~ (m % 60) ~ 'm' if m >= 60 else m ~ 'm' -%}
      {{ (mode ~ ' · ' if mode else '') ~ (('on for ' ~ d) if is_state(entity, 'on') else ('Empty since ' ~ (s | as_local).strftime('%-I:%M %p') if s else 'Empty')) }}
```

A one-row card: the room and its mode, who is there and for how long, the
mode as the icon (amber), and why the room is on as the badge.

```yaml
type: custom:mushroom-template-card
entity: binary_sensor.kitchen_sextant_occupancy
tap_action:
  action: more-info
primary: >
  {{ state_attr(entity, 'room') }} · {{ state_attr(entity, 'mode') or ('Occupied' if is_state(entity, 'on') else 'Empty') }}
secondary: >
  {%- set a = states[entity].attributes if states[entity] else {} -%}
  {%- set s = as_datetime(a.get('since'), default=none) -%}
  {%- set m = ((now() - s).total_seconds() // 60) | int if s else 0 -%}
  {%- set d = (m // 60) ~ 'h ' ~ (m % 60) ~ 'm' if m >= 60 else m ~ 'm' -%}
  {%- if is_state(entity, 'on') -%}
    {{ (a.get('people', []) | map('regex_replace', ' .*', '') | list + a.get('pets', [])) | join(', ') or 'Someone' }} · {{ d }}
  {%- else -%}
    since {{ (s | as_local).strftime('%-I:%M %p') if s else '?' }}
  {%- endif %}
icon: >
  {%- set ns = namespace(i='') -%}
  {%- for w in (state_attr(entity, 'mode') or '') | lower | regex_findall('[a-z0-9]+') if not ns.i -%}
    {%- for re, ic in [['^(movie|film|cinema|theat)', 'mdi:movie-open'], ['^(tv|watch)', 'mdi:television-play'], ['^gam', 'mdi:controller'], ['^(music|party|listen)', 'mdi:music'], ['^(sleep|night|bed)', 'mdi:sleep'], ['^read', 'mdi:book-open-variant'], ['^(work|meeting|call|office)', 'mdi:briefcase'], ['^(cook|dinner|meal|bak)', 'mdi:silverware-fork-knife'], ['^(away|vacation)', 'mdi:airplane'], ['^guest', 'mdi:account-multiple']] if not ns.i and w is match(re) -%}
      {%- set ns.i = ic -%}
    {%- endfor -%}
  {%- endfor -%}
  {{ ns.i or ('mdi:tag' if state_attr(entity, 'mode') else ('mdi:home' if is_state(entity, 'on') else 'mdi:home-outline')) }}
icon_color: >
  {{ 'amber' if state_attr(entity, 'mode') else ('green' if is_state(entity, 'on') else 'disabled') }}
badge_icon: >
  {%- set s = (state_attr(entity, 'sources') or [none])[0] -%}
  {{ {'bluetooth': 'mdi:bluetooth', 'radar': 'mdi:radar', 'media_player': 'mdi:television-play', 'sensor': 'mdi:motion-sensor', 'door': 'mdi:door', 'forced': 'mdi:toggle-switch', 'keep': 'mdi:pin', 'hold': 'mdi:timer-sand', 'restored': 'mdi:restart'}.get(s, '') }}
badge_color: grey
```

The mode icons match the Occupancy page's.

Behind Strimmer: the room sensor named in `entity` is forwarded because
the card names it. The chip also reads each occupant's `person.<name>` for
the picture; it asks Strimmer for `*_sextant_*` and `person.*` itself, and
shows "Waiting for …" until the reconnect brings them. The Mushroom
templates read the pets' `sensor.<pet>_sextant_pet_location`, but Home
Assistant renders templates itself, so they need nothing forwarded. To
avoid the ask and reconnect, list the `person.*` entities in Strimmer's
`always_forward`.

### Who is where

An entities card, one line per person, with how long they have been there:

```yaml
type: entities
title: Who is where
entities:
  - entity: sensor.alex_smith_sextant_person_location
    name: Alex
    secondary_info: last-changed
  - entity: sensor.sam_smith_sextant_person_location
    name: Sam
    secondary_info: last-changed
  - entity: sensor.robin_smith_sextant_person_location
    name: Robin
    secondary_info: last-changed
  - entity: sensor.jamie_smith_sextant_person_location
    name: Jamie
    secondary_info: last-changed
```

The same as a markdown card that writes itself from whatever people exist,
and says how each one was placed:

```yaml
type: markdown
title: Who is where
content: >
  {% for p in states.sensor | selectattr('entity_id', 'search', '_sextant_person_location$') | sort(attribute='name') %}
  {% set a = p.attributes %}
  **{{ p.name | replace(' Location', '') }}** — {{ p.state }}
  {%- if a.source == 'held' %} *(not heard for a bit)*{% endif %}
  {%- if a.source == 'gps' and a.distance_m %} *({{ (a.distance_m / 1000) | round(1) }} km away)*{% endif %}
  {%- if a.source == 'none' %} *(no location)*{% endif %}

  {% endfor %}
```

### A person as a tile

The tile card can show attributes next to the state:

```yaml
type: tile
entity: sensor.robin_smith_sextant_person_location
name: Robin
state_content:
  - state
  - presence
  - floor
```

### The pets at a glance

```yaml
type: glance
title: Pets
columns: 4
entities:
  - entity: sensor.meg_sextant_room
    name: Meg
  - entity: sensor.socks_sextant_room
    name: Socks
  - entity: sensor.fry_sextant_room
    name: Fry
  - entity: sensor.leela_sextant_room
    name: Leela
  - entity: sensor.lilibet_sextant_room
    name: Lilibet
  - entity: sensor.willow_sextant_room
    name: Willow
  - entity: sensor.primrose_sextant_room
    name: Primrose
```

### Where they have been today

```yaml
type: history-graph
title: Rooms today
hours_to_show: 24
entities:
  - sensor.socks_sextant_room
  - sensor.leela_sextant_room
  - sensor.alex_smith_sextant_person_room
```

### Only when it matters

A card that appears while a cat is at the litter boxes, and is gone
otherwise:

```yaml
type: conditional
conditions:
  - condition: state
    entity: sensor.leela_sextant_spot
    state: Litter Boxes
card:
  type: markdown
  content: "🐈 Leela is at the litter boxes"
```

### Cards for the room you are in

The Sextant conditional card shows another card only while the person
viewing the dashboard is in one of some rooms or on one of some floors, so
one dashboard can show the kitchen's cards in the kitchen and the theater's
in the theater. Add the resource `/sextant/sextant-conditional-card.js`
(JavaScript module) once; it has a visual editor like Home Assistant's own
conditional card.

```yaml
type: custom:sextant-conditional-card
rooms: [Kitchen, Butler Pantry]   # in any of these rooms...
floors: [Basement]                # ...or anywhere on these floors
users: [<user id>]                # only for these dashboard users (optional)
person: person.alex_smith         # whose place (optional; default: whoever is viewing)
card:
  type: markdown
  content: "Today's recipes"
```

- The viewer is the person linked to the Home Assistant user (Settings →
  People → the person's user). A user with no linked person, or someone away,
  matches no room or floor.
- Rooms and floors are names as Sextant shows them, either case. A room in
  `rooms` or a floor in `floors` is enough; `users`, when set, must match too.
- With no rooms or floors it is a per-user card.
- While editing the dashboard the inner card always shows.

### Away people on the map

Home Assistant's own map card takes the Sextant device_trackers, so someone
away shows at their GPS position and someone home shows at home:

```yaml
type: map
entities:
  - device_tracker.jamie_smith_sextant
  - device_tracker.robin_smith_sextant
hours_to_show: 12
```

## Things to know

- **`presence` and the room can disagree on purpose.** A person whose things
  have gone `quiet` keeps their last room (`source: held`); the room sensor is
  the best answer for a person who has not left the house. Once they are
  `away`, the room sensors read `unknown` and the location sensor reads the
  GPS zone.
- **GPS sources are per person and in order** (the People card on the Things
  page). A source that is unknown, unavailable, or has not reported for
  `gps_stale_secs` (two hours by default, on the Tuning page) is passed over;
  the sensor's `gps_ignored` attribute and the card say which and why.
- **A restart re-stamps every restored entity as fresh**, so a tracker that
  is frozen looks alive for `gps_stale_secs` after each restart. Put the
  source you trust most first.
- **`last_heard` is not recorded** (it moves every few minutes while a thing
  is heard); `presence` is, so history and the logbook show a thing
  going quiet and coming back.
