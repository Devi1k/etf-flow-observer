from decimal import Decimal

from etf_flow_observer.standardize import parse_decimal, to_shares


def test_wan_fen_becomes_fen():
    shares, unit = to_shares(parse_decimal("2548488.77"), "万份")
    assert unit == "份"
    assert shares == Decimal("25484887700")


def test_wan_fen_with_thousands_separator():
    shares, unit = to_shares(parse_decimal("685,191.66"), "万份")
    assert unit == "份"
    assert shares == Decimal("6851916600")


def test_already_in_fen_is_unchanged():
    shares, unit = to_shares(parse_decimal("100"), "份")
    assert shares == Decimal("100")
    assert unit == "份"
