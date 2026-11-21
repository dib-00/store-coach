"""Rupees at stake are sized on the fall beyond the rest of the city (docs/METHOD.md section 7)."""
from engine.detect import rupees_beyond_city


def test_city_fall_is_taken_off_the_store_fall():
    # ((12.3% - 10.5%) - (13.0% - 12.5%)) x 484 x 9,801 = 13 tenths x 484 x 9801 / 1000 = 61,668 -> 61,700
    assert rupees_beyond_city(0.1233, 0.1054, 0.1297, 0.1245, 484, 9801) == 61700


def test_city_that_did_not_fall_takes_nothing_off():
    # the other stores rose: the store is charged its own fall, never more
    own = rupees_beyond_city(0.1324, 0.1071, 0.1300, 0.1300, 486, 10092)
    rose = rupees_beyond_city(0.1324, 0.1071, 0.1250, 0.1350, 486, 10092)
    assert own == rose == 122600


def test_fall_no_deeper_than_the_city_leaves_nothing_to_send():
    assert rupees_beyond_city(0.1300, 0.1200, 0.1400, 0.1250, 500, 9000) <= 0
