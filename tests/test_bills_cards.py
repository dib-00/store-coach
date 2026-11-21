"""Cards for the "more bills" lever, and the small rules added to the lever's alerts and store blocks."""
from __future__ import annotations

import pandas as pd
import pytest

from engine import bills_cards
from engine.cards import MAX_CARD_WORDS, select_cards, word_count
from engine.checks import numbers_not_in_checks
from engine.load import load
from engine.metrics import Metrics

from .conftest import alerts_of, run_engine
from .synth import make_dataset

AS_OF = "2026-10-31"
CUR = ("2026-10-04", "2026-10-31")


def candidates(folder, as_of=AS_OF):
    return bills_cards.card_candidates(Metrics(load(folder, as_of)))


def move_bills(folder, store, giver, taker, keep_every=4):
    """Hand most of one salesperson's bills to a colleague (from 1 Jul 2026), keeping every 4th."""
    bills = pd.read_csv(folder / "bills.csv", dtype=str)
    mine = bills.index[(bills["store_id"] == store) & (bills["salesperson_id"] == giver) & (bills["bill_date"] >= "2026-07-01")]
    moved = [i for n, i in enumerate(mine) if n % keep_every]
    bills.loc[moved, "salesperson_id"] = taker
    bills.to_csv(folder / "bills.csv", index=False)


# ------------------------------------------------------ A. busy-day attendance
def test_people_missing_the_busy_days_get_an_attendance_card(pack):
    cards = candidates(pack)
    assert [c["salesperson_id"] for c in cards] == ["SP1001", "SP1002"]  # the two planted at AAA-01, nobody else
    c = cards[0]
    assert c["store_id"] == "AAA-01" and c["lever"] == "more_bills"
    assert c["text"] == f"{c['behaviour']} {c['action']}" and c["text"].startswith("Amar, ")
    # 8 weekend days in the window, present on none of them; the named peer was there on all 8
    assert "on 0 of the last 8 weekend and festival days at AAA-01" in c["behaviour"]
    assert c["peer"]["salesperson_id"] in {"SP1003", "SP1004", "SP1005", "SP1006"}
    assert f"{c['peer']['name']} was there on 8" in c["behaviour"]
    # one action for today, with the dates and the festival from the calendar
    assert c["action"].startswith("Today, ask your store manager to roster you on ")
    assert "Sun 1 Nov, Wed 4 Nov (Test Festival), Sat 7 Nov and Sun 8 Nov" in c["action"]
    assert c["priority"] > 0 and c["definition"]


def test_attendance_figures_match_the_roster(pack):
    roster = pd.read_csv(pack / "roster_daily.csv", dtype=str)
    c = candidates(pack)[0]
    by_slug = {k["id"].rsplit(":", 1)[1]: k for k in c["checks"]}
    weekend = pd.to_datetime(roster["date"]).dt.day_of_week >= 5
    in_window = roster["date"].between(*CUR) & weekend & (roster["status"] == "Present")
    assert by_slug["busy_days_present"]["value"] == int((in_window & (roster["salesperson_id"] == "SP1001")).sum()) == 0
    peer = c["peer"]["salesperson_id"]
    assert by_slug["peer_busy_days_present"]["value"] == int((in_window & (roster["salesperson_id"] == peer)).sum()) == 8
    assert by_slug["busy_days_in_window"]["value"] == 8


# --------------------------------------------------- B. bills per day present
@pytest.fixture(scope="module")
def uneven(tmp_path_factory):
    """AAA-02 with SP1009 making a quarter of the bills they did; SP1010 takes the rest."""
    folder = make_dataset(tmp_path_factory.mktemp("uneven"))
    move_bills(folder, "AAA-02", "SP1009", "SP1010")
    move_bills(folder, "BBB-02", "SP1027", "SP1028")  # the same gap in the new store
    return folder


def test_far_fewer_bills_per_day_present_gets_a_card_naming_the_best_peer(uneven):
    cards = {c["salesperson_id"]: c for c in candidates(uneven)}
    assert "SP1009" in cards and "SP1010" not in cards
    c = cards["SP1009"]
    assert c["store_id"] == "AAA-02" and c["peer"]["salesperson_id"] == "SP1010"
    assert c["action"].startswith("Today, serve your first three walk-ins alongside ")
    assert c["peer"]["name"] in c["action"] and c["peer"]["name"] in c["behaviour"]

    # the three figures on the card, by hand from the CSVs
    bills = pd.read_csv(uneven / "bills.csv", dtype=str)
    roster = pd.read_csv(uneven / "roster_daily.csv", dtype=str)
    in_window = bills["bill_date"].between(*CUR)
    present = roster[roster["date"].between(*CUR) & (roster["status"] == "Present")].groupby("salesperson_id").size()
    made = bills[in_window].groupby("salesperson_id").size()
    rate = lambda sp: made.get(sp, 0) / present[sp]
    by_slug = {k["id"].rsplit(":", 1)[1]: k for k in c["checks"]}
    assert by_slug["bills_per_present_day"]["value"] == pytest.approx(rate("SP1009"), abs=0.006)
    assert by_slug["peer_bills_per_present_day"]["value"] == pytest.approx(rate("SP1010"), abs=0.006)
    others = sorted(rate(sp) for sp in ("SP1007", "SP1008", "SP1010", "SP1011", "SP1012"))
    assert by_slug["typical_bills_per_present_day"]["value"] == pytest.approx(others[2], abs=0.006)
    assert rate("SP1009") <= 0.75 * others[2]

    # priority = gap in bills per day present x days present a week x the store's average bill (Rs 9,000 here)
    expected = (others[2] - rate("SP1009")) * (present["SP1009"] / 4) * 9000
    assert c["priority"] == pytest.approx(expected, rel=0.01)


def test_new_store_gets_no_card(uneven):
    assert not [c for c in candidates(uneven) if c["store_id"] == "BBB-02"]


def test_no_card_without_enough_roster_history(uneven):
    # on 31 Jul 2026 the roster (from 1 May) does not reach back over the 13 weeks before the window
    assert candidates(uneven, "2026-07-31") == []


def test_no_card_for_someone_off_the_roster(uneven, tmp_path):
    roster = pd.read_csv(uneven / "roster_daily.csv", dtype=str)
    for name in ("stores", "area_managers", "salespeople", "footfall_daily", "bills", "bill_lines", "items", "calendar"):
        pd.read_csv(uneven / f"{name}.csv", dtype=str, keep_default_na=False).to_csv(tmp_path / f"{name}.csv", index=False)
    gone = (roster["salesperson_id"] == "SP1009") & (roster["date"] > "2026-10-20")
    roster[~gone].to_csv(tmp_path / "roster_daily.csv", index=False)
    assert "SP1009" not in [c["salesperson_id"] for c in candidates(tmp_path)]


# ----------------------------------------------------------- rules for all
def test_every_card_is_within_60_words_and_every_number_has_a_check(pack, uneven):
    cards = candidates(pack) + candidates(uneven)
    assert cards
    for c in cards:
        assert 0 < word_count(c["text"]) <= MAX_CARD_WORDS
        assert numbers_not_in_checks([c["text"]], c["checks"]) == []
        assert c["peer"]["salesperson_id"] != c["salesperson_id"]
        ids = [k["id"] for k in c["checks"]]
        assert len(ids) == len(set(ids)) and all(i.startswith(f"card:{c['store_id']}:{c['salesperson_id']}:") for i in ids)
        assert not any(ch.isdigit() for ch in c["definition"])  # the footnote quotes no figure


def test_cards_reach_the_output_one_per_salesperson(result):
    cards = [c for c in result[0]["cards"] if c["lever"] == "more_bills"]
    assert [c["salesperson_id"] for c in cards] == ["SP1001", "SP1002"]
    assert all(c["word_count"] == word_count(c["text"]) <= 60 and c["definition"] for c in cards)
    assert select_cards([]) == []


# ------------------------------------- the lever's alerts and the store blocks
def test_action_names_the_next_full_weekend_and_any_festival(result):
    a = next(a for a in alerts_of(result[0]) if a["alert_id"] == "AAA-01:more_bills:missed_shifts")
    assert a["action"]["when"] == "Sun 1 Nov, Wed 4 Nov (Test Festival), Sat 7 Nov and Sun 8 Nov"
    by_kind = {}
    for c in a["checks"]:
        by_kind.setdefault(c["kind"], []).append(c)
    dates = by_kind["upcoming_busy_dates"][0]
    assert dates["params"] == {"state": "Uttar Pradesh", "start": "2026-11-01", "end": "2026-11-09"}
    assert dates["value"] == "2026-11-01, 2026-11-04, 2026-11-07, 2026-11-08"
    assert [(c["params"]["date"], c["value"]) for c in by_kind["festival_name"]] == [("2026-11-04", "Test Festival")]


def test_more_bills_alert_says_how_conversion_is_measured(result):
    for a in alerts_of(result[0]):
        if a["lever"] != "more_bills":
            continue
        assert a["definition"].startswith("Conversion is bills divided by walk-ins")
        assert not any(ch.isdigit() for ch in a["definition"].replace(a["store_ids"][0], ""))


def test_store_block_says_why_a_store_is_not_judged(result):
    stores = {s["store_id"]: s for s in result[0]["stores"]}
    assert stores["BBB-02"]["not_judged_reason"] == "Opened 15 Sep 2026; too new to compare with established stores"
    # AAA-03: the door counter read 0 on 10 of the 28 days
    reason = stores["AAA-03"]["not_judged_reason"]
    assert reason.startswith("Footfall is unusable on 10 days of the current window and usable on 18")
    for sid in ("BBB-02", "AAA-03"):
        assert numbers_not_in_checks([stores[sid]["not_judged_reason"]], stores[sid]["summary"]) == []
    for sid in ("AAA-01", "AAA-02", "BBB-01"):
        assert "not_judged_reason" not in stores[sid]


def test_cards_cannot_see_data_after_as_of(pack, tmp_path):
    from datetime import date

    from engine.run import to_json

    poisoned = make_dataset(tmp_path / "poisoned", poison_after=date(2026, 10, 17))
    a, b = run_engine(pack, "2026-10-17")[0], run_engine(poisoned, "2026-10-17")[0]
    assert a["cards"] and to_json(a) == to_json(b)
