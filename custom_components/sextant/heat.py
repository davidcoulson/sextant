"""The Wi-Fi signal map: what each spot in the house actually gets.

The UniFi controller reports, for every wireless client, the signal its
access point hears from it (dBm) and which access point that is. Sextant
knows where some of those clients are: the BLE proxies on Wi-Fi are placed
on the plan, and a phone or a watch has a BLE fix most of the time it is
home. Each such reading is a sample - this floor, this spot, this access
point, this strong - and the samples are pooled in square cells a metre
across. The map draws the cells: how strong the signal is there, and which
access point clients are on there.

It is measured, never predicted: a cell nobody has stood in stays empty.
And it is the signal to the access point the client is on, not to every
access point in reach; for finding dead spots and clients that cling to a
far access point, that is the one that matters.

Devices differ: a watch transmits less than a phone, a phone in a pocket
less than one in a hand. The proxies are fixed and many, so they are the
reference: a moving client's typical offset from what the proxies measured
in the same cell is learned, and taken off its samples.

Pure: no Home Assistant imports. __init__ gathers the readings.
"""
from __future__ import annotations

import math

CELL_M = 1.0
# Samples per cell and access point before the counts are halved, so a cell
# follows the house as access points and furniture move.
CELL_CAP = 200.0
# The store never holds more cells than this (the least recently sampled go).
MAX_CELLS = 8000
# A cell is drawn once it has this many samples.
MIN_SAMPLES = 3
# How fast a moving client's offset is learned, and how far it may go.
BIAS_RATE = 0.05
BIAS_MAX_DB = 15.0
# A reference needs this many proxy samples in the cell for a moving client
# to learn its offset against.
BIAS_MIN_REF = 3
# Readings outside this are not signal levels.
DBM_RANGE = (-110.0, -10.0)
# One sample per client this often, at most.
SAMPLE_EVERY_S = 30.0


def new_store() -> dict:
    """cells: {"floor|ix|iy": {"t": last sample, "aps": {ap mac: [n, sum, n_ref, sum_ref]}}}
    (every sample, and the proxies' alone, each pair halved at CELL_CAP on its own);
    bias: {client mac: dB}; last: {client mac: when last sampled}."""
    return {"cells": {}, "bias": {}, "last": {}}


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def cell_index(x_px, y_px, scale) -> tuple | None:
    """The (ix, iy) of the cell a plan point is in, or None without a scale."""
    if not (_finite(x_px) and _finite(y_px) and _finite(scale) and scale > 0):
        return None
    step = CELL_M * scale
    return int(math.floor(x_px / step)), int(math.floor(y_px / step))


def _key(floor, ix, iy) -> str:
    return f"{floor}|{ix}|{iy}"


def due(store: dict, client, now) -> bool:
    """Whether this client may give another sample now (SAMPLE_EVERY_S)."""
    last = (store.get("last") or {}).get(client)
    return not _finite(last) or now - last >= SAMPLE_EVERY_S or now < last


def add(store: dict, floor, x_px, y_px, scale, ap, dbm, client, now, reference=False) -> bool:
    """One reading into its cell. ``reference`` is a fixed client (a placed
    proxy); a moving one has its learned offset taken off first, and learns
    it from the proxies' samples in the cell. True when it was taken."""
    idx = cell_index(x_px, y_px, scale)
    if idx is None or not floor or not ap or not client or not _finite(dbm) or not DBM_RANGE[0] <= dbm <= DBM_RANGE[1]:
        return False
    cells, bias = store.setdefault("cells", {}), store.setdefault("bias", {})
    key = _key(floor, *idx)
    cell = cells.setdefault(key, {"t": now, "aps": {}})
    row = cell["aps"].setdefault(ap, [0.0, 0.0, 0.0, 0.0])
    value = float(dbm)
    if not reference:
        if row[2] >= BIAS_MIN_REF:
            off = bias.get(client, 0.0)
            off += BIAS_RATE * ((value - row[3] / row[2]) - off)
            bias[client] = max(-BIAS_MAX_DB, min(BIAS_MAX_DB, off))
        value -= bias.get(client, 0.0)
    row[0] += 1.0
    row[1] += value
    if reference:
        row[2] += 1.0
        row[3] += value
    # Each pair ages on its own count: a cell a phone sits in all evening
    # must not wear away the proxy reference the offsets are learned from.
    if row[0] >= CELL_CAP:
        row[0], row[1] = row[0] / 2.0, row[1] / 2.0
    if row[2] >= CELL_CAP:
        row[2], row[3] = row[2] / 2.0, row[3] / 2.0
    cell["t"] = now
    store.setdefault("last", {})[client] = now
    if len(cells) > MAX_CELLS:
        for old in sorted(cells, key=lambda k: cells[k].get("t", 0))[: len(cells) - MAX_CELLS]:
            del cells[old]
    return True


def view(store: dict, floor, scale, min_samples=MIN_SAMPLES) -> list:
    """This floor's cells to draw: [{"x", "y", "size", "dbm", "ap", "n",
    "aps": {ap: [dbm, n]}}], in plan pixels (x, y the cell's top-left). The
    signal is the mean over every sample in the cell; ``ap`` is the access
    point most of them were on."""
    out = []
    if not (_finite(scale) and scale > 0):
        return out
    step = CELL_M * scale
    prefix = f"{floor}|"
    for key, cell in (store.get("cells") or {}).items():
        if not key.startswith(prefix):
            continue
        try:
            ix, iy = (int(v) for v in key[len(prefix):].split("|"))
        except ValueError:
            continue
        aps = {ap: row for ap, row in (cell.get("aps") or {}).items() if row and row[0] > 0}
        n = sum(row[0] for row in aps.values())
        if n < min_samples:
            continue
        total = sum(row[1] for row in aps.values())
        top = max(aps, key=lambda a: aps[a][0])
        out.append({"x": round(ix * step, 1), "y": round(iy * step, 1), "size": round(step, 2),
                    "dbm": round(total / n, 1), "ap": top, "n": int(round(n)),
                    "aps": {ap: [round(row[1] / row[0], 1), int(round(row[0]))] for ap, row in aps.items()}})
    return out


def rooms(cells: list, room_of) -> list:
    """Per room, from a floor's view cells: [{"room", "dbm" (median), "worst",
    "cells", "ap" (the one most cells are on)}], weakest first. ``room_of``
    gives the room a plan point is in, or None."""
    by_room: dict = {}
    for c in cells:
        half = c["size"] / 2.0
        room = room_of(c["x"] + half, c["y"] + half)
        if room:
            by_room.setdefault(room, []).append(c)
    out = []
    for room, cs in by_room.items():
        levels = sorted(c["dbm"] for c in cs)
        mid = len(levels) // 2
        median = levels[mid] if len(levels) % 2 else (levels[mid - 1] + levels[mid]) / 2.0
        aps: dict = {}
        for c in cs:
            aps[c["ap"]] = aps.get(c["ap"], 0) + 1
        out.append({"room": room, "dbm": round(median, 1), "worst": levels[0], "cells": len(cs),
                    "ap": max(aps, key=aps.get)})
    return sorted(out, key=lambda r: r["dbm"])


def clean(data) -> dict:
    """A stored map with only well-formed parts (anything else is dropped):
    a damaged store must cost the map, never the cycle."""
    out = new_store()
    if not isinstance(data, dict):
        return out
    for key, cell in (data.get("cells") or {}).items() if isinstance(data.get("cells"), dict) else ():
        if not isinstance(key, str) or key.count("|") < 2 or not isinstance(cell, dict) or not isinstance(cell.get("aps"), dict):
            continue
        aps = {}
        for ap, row in cell["aps"].items():
            if (isinstance(ap, str) and isinstance(row, list) and len(row) == 4 and all(_finite(v) for v in row)
                    and row[0] > 0 and row[2] >= 0):
                aps[ap] = [float(v) for v in row]
        if aps:
            out["cells"][key] = {"t": float(cell["t"]) if _finite(cell.get("t")) else 0.0, "aps": aps}
    for client, off in (data.get("bias") or {}).items() if isinstance(data.get("bias"), dict) else ():
        if isinstance(client, str) and _finite(off):
            out["bias"][client] = max(-BIAS_MAX_DB, min(BIAS_MAX_DB, float(off)))
    if len(out["cells"]) > MAX_CELLS:
        keep = sorted(out["cells"], key=lambda k: out["cells"][k]["t"])[-MAX_CELLS:]
        out["cells"] = {k: out["cells"][k] for k in keep}
    return out


def wifi_mac_for_proxy(address, clients) -> str | None:
    """The Wi-Fi MAC of the ESP32 a BLE proxy is, among ``clients`` (the
    controller's wireless client MACs): an ESP32's Bluetooth address is its
    Wi-Fi station address plus two, so that one first, then the address
    itself (a proxy that reports its Wi-Fi MAC). None for an Ethernet proxy,
    or anything not on the Wi-Fi."""
    text = str(address or "").strip().lower().replace("-", ":")
    try:
        value = int(text.replace(":", ""), 16)
    except ValueError:
        return None
    if len(text) != 17:
        return None
    for delta in (2, 0):
        cand = value - delta
        if cand < 0:
            continue
        mac = ":".join(f"{(cand >> s) & 0xFF:02x}" for s in range(40, -8, -8))
        if mac in clients:
            return mac
    return None
