"""The weekly cap, the action rule, and the planted stories in the made-up pack."""
from __future__ import annotations

import re

from engine.checks import fmt_inr, numbers_not_in_checks, rupees_at_stake
from engine.load import load
from engine.rank import apply_cap, has_who_what_when, sendable
from engine.run import manager_blocks

from .conftest import alerts_of

GOOD_ACTION = {"who": "Store manager", "what": "Keep six people on the floor", "when": "Sat 7 Nov",
               "text": "Keep six people on the floor on Sat 7 Nov."}


def candidate(i: int, rupees: int, store: str = "AAA-01", action=GOOD_ACTION) -> dict:
    return {"alert_id": f"{store}:more_bills:test:{i}", "rank": 0, "store_ids": [store], "lever": "more_bills",
            "headline": f"issue {i}", "rupees_at_stake_weekly": rupees, "action": action}


# ----------------------------------------------------------------- the cap
def test_cap_keeps_the_five_highest_and_holds_back_the_rest():
    rupees = [3000, 9000, 1000, 7000, 5000, 8000, 2000]
    kept, held = apply_cap([candidate(i, r) for i, r in enumerate(rupees)], 5)
    assert [a["rupees_at_stake_weekly"] for a in kept] == [9000, 8000, 7000, 5000, 3000]
    assert [a["rank"] for a in kept] == [1, 2, 3, 4, 5]
    assert [h["rupees_at_stake_weekly"] for h in held] == [2000, 1000]
    assert all(h["reason"] == "Below the top 5 this week" for h in held)


def test_cap_order_is_stable_on_ties():
    a = apply_cap([candidate(2, 500), candidate(1, 500), candidate(3, 500)], 2)
    b = apply_cap([candidate(3, 500), candidate(2, 500), candidate(1, 500)], 2)
    assert a == b
    assert [x["alert_id"][-1] for x in a[0]] == ["1", "2"]


def test_manager_block_never_exceeds_the_cap_from_the_csv(pack):
    data = load(pack, "2026-10-31")
    blocks = manager_blocks(data, [candidate(i, 1000 * (i + 1)) for i in range(8)])
    am1 = next(b for b in blocks if b["area_manager_id"] == "AM-01")
    assert am1["max_alerts_per_week"] == 5
    assert len(am1["alerts"]) == 5 and len(am1["held_back"]) == 3
    assert am1["alerts"][0]["rupees_at_stake_weekly"] == 8000
    am2 = next(b for b in blocks if b["area_manager_id"] == "AM-02")
    assert am2["alerts"] == [] and am2["held_back"] == []


# --------------------------------------------------------- the action rule
def test_action_needs_who_what_and_when():
    assert has_who_what_when(GOOD_ACTION)
    assert not has_who_what_when(None)
    for missing in ("who", "what", "when", "text"):
        assert not has_who_what_when({**GOOD_ACTION, missing: ""})
        assert not has_who_what_when({k: v for k, v in GOOD_ACTION.items() if k != missing})


def test_alert_without_who_what_when_is_dropped(pack):
    vague = {"who": "", "what": "Improve conversion", "when": "", "text": "Improve conversion."}
    cands = [candidate(1, 9000, action=vague), candidate(2, 100), candidate(3, 5000, action=None)]
    assert [a["alert_id"] for a in sendable(cands)] == ["AAA-01:more_bills:test:2"]
    block = manager_blocks(load(pack, "2026-10-31"), cands)[0]
    assert [a["alert_id"] for a in block["alerts"]] == ["AAA-01:more_bills:test:2"]
    assert block["held_back"] == []  # dropped, not merely held back


def test_real_drop_with_no_buildable_action_is_not_sent(result):
    output, notes = result
    assert not [a for a in alerts_of(output) if "BBB-01" in a["store_ids"]]
    assert any(n.startswith("BBB-01:") and "no action naming who, what and when" in n for n in notes)


# ------------------------------------------------------ the planted alert
def test_missed_shifts_alert_is_raised_with_a_concrete_action(result):
    output, _ = result
    alerts = alerts_of(output)
    assert [a["alert_id"] for a in alerts] == ["AAA-01:more_bills:missed_shifts"]
    a = alerts[0]
    assert a["scope"] == "store" and a["cause_code"] == "missed_shifts" and a["rank"] == 1
    assert a["salesperson_ids"] == ["SP1001", "SP1002"]
    assert has_who_what_when(a["action"])
    for name in ("Amar V.", "Bina V."):
        assert name in a["action"]["text"]
    # the upcoming busy days come from the calendar: the weekend and the festival on Wed 4 Nov
    assert a["action"]["when"] == "Sun 1 Nov, Wed 4 Nov and Sat 7 Nov"


def test_every_number_in_the_alert_text_has_a_check(result):
    for a in alerts_of(result[0]):
        texts = [a["headline"], a["cause"], a["action"]["text"], a["arithmetic"]["worked"]]
        assert numbers_not_in_checks(texts, a["checks"]) == []
        ids = [c["id"] for c in a["checks"]]
        assert len(ids) == len(set(ids))
        assert set(a["arithmetic"]["input_check_ids"]) <= set(ids)


def test_a_number_without_a_check_is_caught():
    checks = [{"display": "10.7%"}, {"display": "₹1,22,600"}, {"display": "Sun 1 Nov 2026"}]
    assert numbers_not_in_checks(["BLR-03 converts 10.7% on Sun 1 Nov, worth ₹1,22,600."], checks) == []
    assert numbers_not_in_checks(["BLR-03 converts 10.8% of walk-ins."], checks) == ["10.8"]


def test_rupees_follow_from_the_displayed_inputs(result):
    for a in alerts_of(result[0]):
        by_id = {c["id"]: c for c in a["checks"]}
        bench, cur, walk, abv = (by_id[i] for i in a["arithmetic"]["input_check_ids"])
        assert a["rupees_at_stake_weekly"] == rupees_at_stake(bench["value"], cur["value"], walk["value"], abv["value"])
        # a judge multiplying what is displayed lands within 1% of what is displayed
        num = lambda s: float(re.sub(r"[^\d.]", "", s))
        by_hand = (num(bench["display"]) - num(cur["display"])) / 100 * num(walk["display"]) * num(abv["display"])
        assert abs(by_hand - a["rupees_at_stake_weekly"]) <= 0.01 * a["rupees_at_stake_weekly"]
        assert a["arithmetic"]["worked"].endswith(f"= {fmt_inr(a['rupees_at_stake_weekly'])} a week")


def test_rupee_arithmetic_by_hand():
    # (13.2% - 10.7%) x 486 x 10,092 = 122,617.8 -> nearest 100
    assert rupees_at_stake(0.1324, 0.1071, 485.5, 10092.04) == 122600
    assert fmt_inr(122600) == "₹1,22,600"


def test_new_store_is_flagged_and_not_judged(result):
    output, _ = result
    new = {s["store_id"]: s["is_new_store"] for s in output["stores"]}
    assert new == {"AAA-01": False, "AAA-02": False, "AAA-03": False, "BBB-01": False, "BBB-02": True}
    assert not [a for a in alerts_of(output) if "BBB-02" in a["store_ids"]]


def test_cause_that_cannot_be_sent_is_not_replaced_by_another(tmp_path):
    import pandas as pd

    from .conftest import run_engine
    from .synth import make_dataset

    folder = make_dataset(tmp_path / "pack")
    # Names with digits in them put numbers into the text that no check backs,
    # so the text gate must refuse the missed-shifts alert at AAA-01 ...
    people = pd.read_csv(folder / "salespeople.csv", dtype=str)
    people["name"] = ["Person" + sp[2:] + " Q." for sp in people["salesperson_id"]]
    people.to_csv(folder / "salespeople.csv", index=False)
    output, notes = run_engine(folder, "2026-10-17")
    # ... and the store must not then be given a different cause instead.
    assert alerts_of(output) == []
    assert any("AAA-01:more_bills:missed_shifts: not sent, figures without a check" in n for n in notes)
