[Sextant](../README.md) › Proxies

# Proxies

![The Proxies page: every proxy grouped by floor and room with a health count per group](../img/screenshots/sextant-proxies.png)

Every placed proxy grouped by floor and room, with a count per group of
online, quiet (no reading for two minutes), offline and unmatched (placed
but no scanner by that name or address). A proxy is **behind** when its
ESPHome or ble-proxy version is older than the one most proxies run: an
update that failed or never reached it. Only ble-proxy builds are compared;
wall tablets and vendor firmware keep their own versions. Each row shows its firmware, the
last time it heard anything, its calibration correction and its height. A second card
lists what each proxy hears right now, so a proxy that is up but not
scanning stands out.

The **self-test** takes each proxy in turn, hides it, locates it from the
other proxies' readings of its beacon, and measures how far that lands from
where you placed it. The result is broken down by floor and by room (median
and CEP95, the worst proxy in each), with rooms that have no proxy in them
listed as such: a whole-house figure hides exactly which rooms the proxies
place well. A proxy the others agree is somewhere else is called out above the table:
at least five proxies hear it, their ranges meet at a spot 3 m or more from
where it is drawn, and they fit that spot at least twice as well as the
drawn one. That is usually a proxy placed in the wrong room or on the wrong
side of one. **Move it there** redraws it at that spot (the plan it replaces
is kept under History on the Edit page); check it first, because a proxy
behind a thick wall or in a metal box can read far away while drawn right.
The whole-house CEP95 is published as
`sensor.sextant_position_accuracy` (metres) with per-floor and per-room
figures in its attributes; the full detail is at `/api/sextant/selftest`.
The self-test works from the calibration sample window, so a floor only has
figures once it has been sampled: a manual run samples one floor and
replaces the window, while **Auto calibration** keeps every floor sampled
in a rolling six-hour window. Turn it on if you want the whole house
covered.

**Wi-Fi signal by room** ranks the rooms by the median of their
[Wi-Fi signal](live.md#wi-fi-signal) squares, weakest first. Each row
shows the weakest square and the access point most squares are on. Below
the table are the sample count, each device's learned offset, and **Start
over**, which drops every sample. Use it after moving or replacing an access
point.
