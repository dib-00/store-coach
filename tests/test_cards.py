"""The 60-word limit and one-card-per-salesperson rule."""
from engine.cards import MAX_CARD_WORDS, select_cards, word_count


def cand(sp="SP1", words=40, priority=100.0, lever="bigger_baskets", peer="SP2"):
    return {
        "store_id": "TST-01",
        "salesperson_id": sp,
        "salesperson_name": "Test A.",
        "lever": lever,
        "behaviour": "b",
        "peer": {"salesperson_id": peer, "name": "Peer B."},
        "action": "a",
        "text": " ".join(["word"] * words),
        "checks": [],
        "priority": priority,
    }


def test_card_at_the_limit_is_kept_and_over_the_limit_is_dropped():
    assert MAX_CARD_WORDS == 60
    cards = select_cards([cand("SP1", 60), cand("SP3", 61)])
    assert [c["salesperson_id"] for c in cards] == ["SP1"]
    assert cards[0]["word_count"] == 60


def test_no_emitted_card_is_over_60_words():
    cards = select_cards([cand(f"SP{i}", w) for i, w in enumerate([1, 30, 59, 60, 61, 75, 200])])
    assert cards and all(word_count(c["text"]) <= 60 for c in cards)


def test_one_card_per_salesperson_highest_priority_first():
    cards = select_cards([cand("SP1", 20, 10.0, "more_bills"), cand("SP1", 20, 500.0, "more_repeat")])
    assert len(cards) == 1 and cards[0]["lever"] == "more_repeat"


def test_over_limit_candidate_falls_back_to_a_shorter_one():
    cards = select_cards([cand("SP1", 80, 900.0, "more_repeat"), cand("SP1", 30, 10.0, "more_bills")])
    assert len(cards) == 1 and cards[0]["lever"] == "more_bills"


def test_peer_must_be_named_and_must_be_someone_else():
    assert select_cards([cand("SP1", peer="SP1")]) == []
    bad = cand("SP4")
    bad["peer"] = {"salesperson_id": "", "name": ""}
    assert select_cards([bad]) == []
