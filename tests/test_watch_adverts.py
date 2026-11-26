"""Apple manufacturer data split into messages (sextant.watch_adverts)."""
import sextant  # noqa: F401
from sextant import watch_adverts as wa


def test_nearby_info_is_found_among_other_messages():
    data = bytes.fromhex("0c0e" + "11" * 14 + "1005" + "3b1c" + "aabbcc")
    assert [k for k, _ in wa.messages(data)] == [0x0C, 0x10]
    assert wa.nearby_info(data) == [3, 0xB, 0x1C]


def test_cut_short_or_missing_messages_give_nothing():
    assert wa.messages(bytes.fromhex("1005aa")) == []
    assert wa.nearby_info(bytes.fromhex("0c0100")) is None
    assert wa.nearby_info(b"") is None
