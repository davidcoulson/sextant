[Sextant](../README.md) › How positioning works

# How positioning works

Each cycle (15 s by default) runs this pipeline per thing.

**Distances.** Bermuda's smoothed distance per proxy, or with
`distance_estimator: median` the median of the recent raw RSSI samples
converted with Bermuda's own path-loss parameters, which is symmetric where
Bermuda's running minimum reads far proxies short. Calibration factors and
the proxy and thing heights are applied here: a slant range becomes a
horizontal one before it reaches the solver. Readings under 0.5 m are
weighted as "right here" rather than by 1/r².

**Which proxies.** Every proxy within `solver_near_always` metres plus the
nearest `solver_max_receivers`, dropping readings beyond `solver_max_range`
once three remain. Beyond eight metres a BLE range is mostly noise.

**The fit.** A bounded, robustly weighted least-squares trilateration in
pure numpy (`solver_numpy.py`, benchmarked against SciPy on a 48-proxy
layout), run in the executor. Spiky readings are down-weighted rather
than dropped. A fix that lands outside every room is snapped to the
nearest room, unless it stays more than `outside_margin_m` beyond every room for
`outside_secs`, when the thing reads **Outside** instead (`kind: outside`, and
`outside_m` in its fix). A dog has a second way out, since a garden fix lands
in a room all the same (no proxy out there pulls it out): heard by no more
than `outside_faint_prox` proxies with the nearest `outside_faint_m` or more
away, for `outside_secs`, it reads **Outside** too, and comes back in once a
proxy is within `outside_near_m`. And once no proxy hears her at all, a dog whose GPS tracker (her collar, set on the People card) says home reads **Outside** rather than home. Never for a cat. A fix in a no-go area is snapped out of it, to the room the
thing is already in while that room's wall is within 1.5 m of the nearest one
(a fix inside a void is no evidence for either side of it).

**Fingerprints.** Every proxy that advertises is heard by every other
proxy, so Bermuda continuously measures a labelled vector of ranges at a
known position: one reference fingerprint per proxy, for free. With
`position_estimator: fused` (the recommended setting once the reference
database has a minute of samples) a thing's vector of ranges is matched
against those references and the fix is blended,
`(1 - fingerprint_weight) × fit + fingerprint_weight × fingerprint`. A
wall that makes a proxy read the thing long makes it read the references
behind that wall long too, and the comparison cancels it. The gain
between probe beacons and things is learned from the things themselves
(`fingerprint_auto_gain`): a shared gain, plus a faster multiplier per
thing, because a watch reads weak and a Tile reads hot. It is published
per fix as `fp.gain`. A match whose scale still disagrees with the thing
counts for less (`fp.trust`, zero at a factor of three). A floor with only
one or two proxies can compete on its fingerprint. Any thing can opt out
from its dialog on the Things page: **Positioning** is the estimator for
that thing alone, so a tag the fingerprint makes worse can be geometric
only.

**Smoothing.** A constant-velocity Kalman filter on the position, in
metres so it behaves the same on any plan resolution; it resets on a floor
change or an absence.

**Floors.** Every floor with three or more proxies hearing the thing is
solved and scored by how well its fit explains all of its proxies. A
through-ceiling reading fits one proxy and contradicts the rest. Scores
are scaled by proximity (the mean of the `floor_proximity_k` nearest
distances on this floor, or the nearest alone when it reads under
`floor_proximity_near_m`, against the best competing floor; `gated`, or the
weighted `geometric` mean of fit and proximity, see
[`floor_proximity_blend`](tuning.md)) and by the floor's `bias`, then
smoothed; a challenger must lead for `floor_switch_secs`, by a margin that
grows with the incumbent's tenure, or by any amount without a break for four times as long. All the smoothing here (floors, rooms,
spots) and the hold timers are per second of wall clock, tuned at the 15 s
cycle, so a faster refresh gives more fixes rather than jumpier ones.

A proxy mounted between storeys - a basement ceiling light a foot and a half
under the floor above - hears the room overhead about as well as its own. Turn
off *Use for floor choice* in its panel on the Edit page and it still helps
place things on its own floor, but it no longer counts toward which floor wins:
it is left out of the proximity term, of the nearest-proxy test that decides
which floors are solved at all, and of the fit score's corroboration. A
floor whose proxies are all position-only is scored on them anyway.

**Bias fields.** A floor's `bias` is one prior for the whole plan, and a
house is not uniform. Over a slab the floor below is attenuated and the
election has an easy time. Beside a void — a catwalk over a foyer, a gallery
over a great room — both floors hear the thing line-of-sight, fit it equally
well, and nothing in the evidence separates them. So a floor can carry a
*bias field*: a coarse grid of multipliers over its plan, sampled where
**that floor's own solve** put the thing, and multiplied onto the scalar.
Paint the catwalk up ("a fix that lands here is to be believed") and the
void itself down ("there is no floor here to stand on"). Because a field is
only ever read at its own floor's fix, it needs nothing to line one floor's
plan up against another's. It is sampled bilinearly, so a fix jittering
across a cell edge moves the bias smoothly instead of flickering it.

**Registration.** Pins placed on the [Edit page](edit.md#lining-the-floors-up)
- the same named point on two or more floors - give each floor a rigid
motion into one *house frame* in metres, and an `elevation` gives it a
height. The fit holds each floor's measured scale and reports the scale the
pins imply rather than absorbing the difference, so a drawing error shows up
as a number instead of hiding inside the alignment. Registered floors
publish each candidate fix in house coordinates as well.

A flat field is all ones and changes nothing, to the last digit — lay it
first, confirm nothing moved, then shape it. Set it with
[`sextant.set_floor_bias_field`](automation.md#services). Every cycle
publishes each contending floor's own fix and score as `floor_cands`, and
`tools/floor_field_replay.py` re-scores a log of those under a proposed
field, so a stroke can be graded against what really happened before it
ships.
`election_log_hours` on the Tuning page keeps those cycles on disk, and
`tools/replay_floors.py` replays the whole election - margin, dwell,
proximity weight - over them (see [Tuning](tuning.md)). While it records,
each floor's entry also carries `cross`: the fix that floor would have
had with the other floors' proxies helping (their plan positions carried
through the pins, the slant shortened by the storey between them, half
weight, 6 m at most). It is logged only; nothing is placed by it yet.
`tools/replay_cross_floor.py` reads the log and says which fix was
steadier, more often in the published room, and closer to the proxy a
thing was sitting on.
`tools/receiver_report.py` reads the same log and lists, per receiver,
how often it was in the elected floor's fix and how far its ranges sat
from that fix (a steady bias means a misplaced or miscalibrated
receiver), with the placed receivers that never took part. The Health
page shows the same report for the last six hours under **Receivers
against real fixes**. Finished hours of the log are gzipped; the tools
read both.

**Rooms.** Membership, not a point test: samples on the filter's error
ellipse are attributed to rooms and the shares smoothed. The current room
holds until a challenger leads by `zone_switch_margin` for
`zone_switch_secs` - or, when the challenger is not next door (its
outline more than 2.5 m from the current room's, the same rule the
far-move KPI counts by), by `far_move_margin` for `far_move_secs`:
walking there passes through the rooms between, which a real move shows
and a fix that jumped does not. A thing slower than `stationary_speed` for
`stationary_secs` is on a table and its room locks - but only a room it
has earned, held for that long already and still the best-supported, so a
first guess after a restart is never frozen. It unlocks after
`zone_unlock_secs` more than `zone_unlock_margin` outside, when it clearly
moves, or when the locked room has kept under a tenth of the evidence for
twice `zone_unlock_secs`: the lock holds through jitter on a boundary, not
through the thing being somewhere else.

**Across a restart.** A cycle's state - each thing's filter, its room and
spot elections with their smoothed probabilities and timers, the proxy it
is anchored to, and when it arrived where it is - is written to `.storage/sextant_runtime` every two
minutes and again on a clean stop. A restart reads it back and carries on,
as a starting point the next readings can disagree with, so a thing keeps
its room and its spot instead of re-earning them and a person does not
follow whichever of their things settles first. Past `restore_state_secs`
(five minutes) the elections are stale and only each thing's last sighting
is kept, which is what the Live page shows as *away since*.

**Spots.** The same election scaled down: the share of the ellipse inside
each spot of the elected room, entered at `subzone_enter_prob`, left at
`subzone_unlock_margin` outside, every change waiting
`subzone_switch_secs`. Two things speak beside that share, each lifting it
to at least their own strength: a [proxy on the spot](edit.md) that hears
the thing close and clearly nearest, and the share of a fingerprint fix
that came from [pins](live.md#location-pins) inside the spot. The pins
matter where the proxies cannot help - a cat lying on a couch makes the
couch's own outlets read about twice too far - and only speak for a thing
on or beside the spot, since pins are shared by a class. A locked room
keeps its spot while the fix stays within `subzone_lock_release_m` of it:
a still thing's fix wanders, often further than a bedside table is wide,
but a pet that crossed the room has really left. A spot can be limited
to certain [classes](things.md) — a bedside table to a phone, a watch and
keys, a cat bed to the cat — and is then not a candidate for anything else
at all, so the cat bed never competes for the phone. A spot with no classes
set takes any thing, which is how every spot drawn before this behaves.
Three of the classes stand for a family: **Person** also takes a man, a woman
or a child, **Pet** also takes the dog or the cat, and **Bag** also takes a
backpack, a purse or a piece of luggage. The picker shows the
members of a family you have picked outlined, so a spot's real reach is on
the screen. It does not work the other way round — a spot asking for Man is
not satisfied by something classed merely Person.

**Near-field anchor.** A thing one proxy reads inside `anchor_max_m`
with every other proxy at least `anchor_ratio` times farther, for
`anchor_secs`, is placed on that proxy: a watch on the bedside table next
to its proxy, not 1.7 m away where the far proxies' errors pull the fit.
Released once the reading opens past `anchor_release_m`, or another proxy
reads the thing closer, for `anchor_secs`.

**Calibration.** Probe-to-probe ranges against the placed positions (3D
when both proxies have heights) solve a per-proxy multiplier, normalised so
they never rescale everything at once. A multiplier is exactly a
per-scanner RSSI offset in Bermuda's model, which is how
`calibration_target: bermuda` writes it.

## Routine: where a thing usually is

Sextant counts the time each thing spends in each room, by weekday or weekend and hour of the day, from the rooms it is confident about, and forgets with a half-life of three weeks. A thing on the line between two rooms then switches a little more easily into the room it is usually in at that hour and a little less easily out of it (`habit_margin_gain`, 0.1: at most that much on the lead a challenger needs). It never overrides clear evidence, needs about 20 minutes in an hour slot before it says anything, and is kept in `.storage/sextant_habits`. Set `habit_margin_gain` to 0 to turn it off; delete that file to start over.

The pull is set per class: in a thing's dialog on the Things page, "Routine pull for every <class>" (0 to 0.3). Blank uses `habit_margin_gain`, except pets, which default to none because a tag on a dog or cat has no routine to lean on. Every thing still learns its own history either way.

The same history can weigh the floor election too (`habit_floor_weight`, 0 = off by default). Each floor's score is multiplied by the share of this hour the thing is usually on that floor, raised to the weight, and a floor it is never on at that hour still counts as 5%. At 0.25 a dog asleep upstairs at 03:00 nine nights in ten has its upstairs score multiplied by about 0.97 and the ground floor's by about 0.56, which holds it upstairs through the readings that dip, while a plain walk downstairs still wins. It is set per class in a thing's dialog ("Floor routine for every <class>", 0 to 1; blank uses `habit_floor_weight`), so it can be tried on the dogs first. It is skipped while the thing's charging sensor says it is charging, and for a watch whose advert says it is off a wrist: either sits where it was put, not where its owner usually is. The election log shows each floor's factor as `habit`. It only applies at an hour when one floor has at least `habit_floor_min_share` (0.7) of the thing's time: a cat that roams the house in the afternoon has no floor to be held to then. Replayed over 40 hours of the election log at weight 0.2, a gate of 0.6 to 0.75 kept a dog's nights upstairs right and halved the extra cat moves the prior missed without it; 0.8 lost the nights.

Spots are counted the same way, inside rooms the room election is sure of. They pull nothing yet; with the rooms and floors they show as the `usual_*` attributes on a thing's sensors (see [automation](automation.md)).

A holiday or a day off is not the routine. `sextant.pause_habits` stops both pulls and the learning until a time (`until`) or for a number of `hours`, for some `things` or `classes` or, with neither, for everything; `sextant.resume_habits` ends every pause. Pauses are stored with the floor plan, so they survive a restart. `sensor.sextant_habit_pauses` counts the pauses running; its `pauses` attribute lists each one's end and the things or classes it covers, and `until` is when the last one ends. An automation can call it from a holiday calendar:

```yaml
triggers:
  - trigger: calendar
    event: start
    entity_id: calendar.holidays
actions:
  - action: sextant.pause_habits
    data:
      until: "{{ trigger.calendar_event.end }}"
```
