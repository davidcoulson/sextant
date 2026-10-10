

def test_dump_rounds_are_spaced_further_apart():
    from sextant import calibration as cal_mod
    assert cal_mod._round_gap(10, "ranging") == 10
    assert cal_mod._round_gap(10, "dump") == 10 * cal_mod.DUMP_INTERVAL_FACTOR
