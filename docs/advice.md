[Sextant](../README.md) › Advice

# Advice

![The Advice page: one change plan per floor, worst floor first, each with its own tally and a button that marks every suggested spot on the plan](../img/screenshots/sextant-advice.png)

Which rooms the proxies serve worst, and where one more would help. Press
**Analyse the house** and every room on every floor is judged two ways:

- **measured**: in the self-test, how far the proxies placed in the room land
  from where they are placed (median, and the worst one);
- **geometric**: for a grid of points inside the room, how far away the
  third-nearest proxy on the floor is (a fix needs three) and whether the
  three nearest all sit to one side of the point.

Each room also shows how much it is used, from the person log (the last 48
hours unless `person_log_hours` on the [Tuning](tuning.md) page says
otherwise):

- **Time here**: the room's share of the time people were placed in the
  house. Pets that are tracked as persons count too. Time away, or home with
  no room known, is left out; time Outside is counted, so the rooms need not
  add up to 100%.
- **Bounces**: how many times someone was put into this room, or out of it,
  and straight back within two minutes. A person rarely does that; a
  position that cannot settle between two rooms does. A bounce counts for
  both rooms, because the log cannot say which of the two the person was in.

A dash means the log never names the room: nobody was placed there, the log
is off, or it has only just started (the log records a person's room from
the version that added these columns on, so they fill over the first two
days). A dash is not a zero.

The rooms are grouped into one change plan per floor. The rooms that need
something are listed most used first, so poor coverage where people spend
their day comes before a closet with no proxy; rooms with the same use, or
none recorded, are worst issue first. The floors follow the same order: the
floor whose flagged rooms are used most first, then worst floor first (a
floor ranks by its single worst room, ties broken by how many proxies it
needs). Each floor heading carries its own tally — how many rooms are
flagged and how many proxies to add — so a floor is one trip up the stairs
with one list.

Each room gets an issue:

| Issue | Meaning | What it suggests |
|---|---|---|
| no proxy | nothing placed in the room | a wall spot, unless the neighbours' proxies already reach all of it |
| weak proxy | one proxy lands far off while the rest of the room is fine | check that proxy is where the plan shows; move it off metal and out of cupboards |
| coverage | part of the room has its third proxy more than 5 m away | one or two wall spots, chosen one at a time to cover what is still uncovered |
| one-sided | the three nearest proxies sit to one side for most of the room | the same |
| noisy | covered, but every proxy in the room lands 2 m or more off | check the floor's scale and each proxy's position, set mount heights; one far-wall spot for a fourth opinion |
| ok | under 2 m and covered | nothing |

Suggested spots sit just inside a wall, where an outlet or a switch would
be. **Show on plan** opens the Edit page on that floor with one room's
spots marked, and **Show all N on this floor** marks every spot the floor
needs at once, each ring labelled with its room — the whole floor's work in
one view before you pick up a drill. The plan fades back behind the rings
while they are shown, and they are numbered, so four suggestions are not
something to hunt for among sixty proxies. Placing a proxy there is the usual
Place tool. Proxies Bermuda hears that sit on no floor are listed at the
top, each with the spot that needs it most.

Like the self-test, the analysis works from the calibration sample window,
so keep **Auto calibration** on for it to see every floor.

## Location pins

A location pin ("It's actually here…" on the [Live](live.md) page) is the
best help a place can get: fixes within about 2 m of a pin land much
closer. A pin in the wrong place does the opposite and pulls everything
near it the wrong way. **Check pins** looks for both. (A pin only guides a
thing whose position uses the fingerprint match. **Apply best fit** after
pinning turns that on when it lands closer.)

**Pins to look at again** lists a pin when:

- the pins it guides land further off with it than without it (half a
  metre or more on average, and more of them worse than better). One of
  the two may be in the wrong place, or the two places may look alike to
  Bluetooth; the row names the neighbour it disagrees with most, so check
  both;
- its own readings put the thing 6 m or more from the pin, and at least
  twice as far as your pins usually read, so the thing was probably not
  there for the whole time the pin was taken from;
- it is a copy of another pin, made from exactly the same readings.

**Forget** removes a pin for good. A pin the check lists is worth a look,
not proof: forget it if you are not sure the thing was there, and pin the
place again next time.

**Places without a pin** lists where a thing has spent two hours or more of
the history Sextant keeps with no pin within 2 m. **Show on plan** rings the
place. The ring is where Sextant put the thing, which is only roughly where
it was, so pin it at its real spot the next time it is there.

## Scanners you leave off the plan on purpose

A kiosk, a test board or an outdoor proxy shows up under "Heard but not
placed" on this page and on Proxies for as long as Bermuda hears it. Click
**Ignore** next to it and both lists leave it out; the ignored ones are
listed under the row with an **Un-ignore** button. The list is kept in the
layout, so it survives edits and restarts.
