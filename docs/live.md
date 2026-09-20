[Sextant](../README.md) › Live

# Live

The floor plan with every tracked thing drawn as an avatar in its own colour, the
same colour as its row in the list. Click a thing (row or avatar) to
focus it: everything else fades, it grows a halo, the panel switches to its
floor, and the side panel shows its room, spot, floor, the proxy it is
anchored to if any, and every proxy that hears it with the distance; a
**Details** disclosure holds the floor odds, spot shares, confidence,
estimator telemetry, trust and speed. **Edit** (administrators) opens the
thing's dialog on the Things page - name, class, colour, photo, height -
without hunting for it in the list. A **blend slider** from geometric to
fingerprint sets how this thing's position is estimated (the two ends
are drawn on the map when the fingerprint switch is on), and **It's
actually here…** records a [location pin](live.md#location-pins). A thing with no fix shows *seen 40s
ago* rather than a blank. Switches draw the solver's distance circles, the
fingerprint fix, a trail, and hide the plan image. A history scrubber under
the map replays where a thing has been over the retention window, with a
room band, playback and a jump-to-time picker.

**Ghosts.** A thing nothing has heard for `stale_after_secs` (two minutes
unless you change it on the Tuning page) is drawn as a ghost: faint, with a
dashed outline and *3m ago* under it, and its row in the list fades with a
ghost icon. What you are looking at is where it *was*; the room and spot
sensors still say the same, because nothing has contradicted them yet. It
leaves the map altogether after `position_timeout` (five minutes by
default). The dashboard card draws ghosts the same way.

**How long it has been there, and where it has been.** The focused thing's
card says how long it has been where it is - *Meg's Cafe for 1h 12m, since
2:41 pm*, and when that is a spot, how long it has been in the room around
it too. Below is the **timeline**: the last day as a band, one colour per
room (a spot is the darker shade of its room, a stretch nobody heard it is
hatched), then the stays newest first with their times and lengths. A `+`
means the stay began before the start of what history keeps, so it is at
least that long. Stays come from the position history, which records a
point on every room and spot change.

On a phone the map switches (labels, trails, the grid and so on) collapse
behind a single options button so they never force sideways scrolling, the
floor picker and the cycle-age clock move to a bar under the page, and a
row of **quick actions** — self-test, and for an administrator, adding a
thing and starting calibration — jumps straight to the right page
without hunting through the tabs. Editing the floor plan itself is still
a desktop job.

## Grouped by person

When things have owners (**Belongs to** on the Things page), each person
gets a heading in the list - their picture, their name, and under it where
their own location sensor puts them - and a click on the heading folds the
group away. One thing is enough for a section; only a pet whose one thing
is its own tag stays a plain row. Those rows - the cats and the dog - come
next under **Pets**, and the rest follow under **Everything else**.

## Quick actions

Selecting a thing opens a row of buttons inside its row in the list:
**It's here** (a location pin, with the floor's spots to zoom to),
**Activity** (where it has spent its time; again to hide it), **History** (scrub it),
and **Edit**, which opens the thing on the Things page.

## Location pins

When a thing sits in the wrong place, select it on the Live page, click
**It's actually here…** and tap the spot on the map where it really is.
On a phone, pinch to zoom, or tap one of the floor's spots listed under
the prompt to fill the screen with just that spot (a bedside table
becomes phone-sized); **Whole floor** zooms back out. The pin goes down
when your finger lifts without moving, so panning or pinching never
places one.
Sextant keeps the solver inputs of the last few minutes for every
thing, so it re-solves those cycles under every blend of geometric fit
and fingerprint match and every reference gain, and shows how far each
lands from your pin and how often it gets the room right. **Apply** on a
row makes those the thing's settings (its blend weight, and a gain
multiplier folded into its learned gain). One pin can overfit, so pin a
thing in two or three rooms.

A pin inside a spot is also evidence of being in that spot: a fix is the
weighted blend of the pins and proxies it matched, and the share of that
blend sitting inside the spot counts the way a proxy on the spot does - but
only for a thing whose own fix is on or beside that spot, since pins are
shared by a class and a cat across the room still matches the couch's.
This is what gets a cat onto a couch - lying on it, the cat's own body
makes the couch's outlets read about twice too far, while the pins still
match.

A pin keeps the readings as Bermuda gave them, before calibration and
per-thing trims, and applies whatever corrections are in force each time
it is used, so re-running calibration or changing the close-range fade
never leaves a pin describing yesterday's corrections. Pins made before
3.17.7 have the correction then in force divided back out, assumed to be
the one in force now: re-pin a spot that matters if calibration has
changed since.

A pin guides the thing that made it and things of the same class - the
cats share one another's pins, a phone's pin helps the other phones -
and nothing else: a pin records how one device looks from one place, and
a watch on a wrist does not look like a phone in a hand
(`fingerprint_marks_scope`: `own`, `class` or `all`).

Pins stay, with their samples, in `.storage/sextant_truth`, and do two
more jobs. The Tuning page's **Accuracy** card re-solves every pin under
the settings in force and reports, per thing, the mean error in metres
and the share of cycles in the right room: the accuracy figure the
stability KPI cannot give. And each pin becomes a fingerprint reference
at the pinned point, in the pinning thing's own scale, so rooms with no
probe nearby get a reference too (`fingerprint_marks` turns that off).

## Activity

With a thing selected, **Activity** colours the plan by how long
it spent in each half-metre square over the last hour, 6 hours, day or
week, blended into a smooth wash: blue for passing through, red for the
longest stay. The note beside
it gives the time on this floor, the longest stay in one square, and the
time on other floors. A reading holds until the next one for at most five
minutes, and a dropout counts for one minute, so a thing that went quiet
does not pile hours onto its last square. History keeps 6 hours by
default; **History kept (hours)** on the Tuning page raises it, up to a
week. Asking for more than is kept says how far back it goes.

