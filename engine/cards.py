"""Salesperson cards: one per salesperson, 60 words or fewer.

Each lever module offers card candidates; this module picks at most one per salesperson
(the one with the most rupees a week behind it) and enforces the word limit.

A card candidate is a dict with:
    store_id, salesperson_id, salesperson_name, lever,
    behaviour  the one behaviour, as a sentence
    peer       {"salesperson_id", "name"}  a named peer from the SAME store
    action     the one action for today, as a sentence
    text       the whole card as shown (behaviour, peer, action), 60 words or fewer
    checks     every number quoted in the text, as Check dicts
    priority   rupees a week the behaviour is worth (used only to choose between candidates)
    definition (optional) how the quoted figure is defined; shown as a footnote, not part of the 60 words
"""
from __future__ import annotations

MAX_CARD_WORDS = 60
REQUIRED = ("store_id", "salesperson_id", "salesperson_name", "lever", "behaviour", "peer", "action", "text", "checks")


def word_count(text: str) -> int:
    """Words are whitespace-separated tokens, the same rule the web app uses."""
    return len(text.split())


def is_valid_card(c: dict) -> bool:
    if any(k not in c for k in REQUIRED):
        return False
    if not all(isinstance(c[k], str) and c[k].strip() for k in ("behaviour", "action", "text")):
        return False
    peer = c["peer"]
    if not peer or not peer.get("salesperson_id") or not peer.get("name"):
        return False
    if peer["salesperson_id"] == c["salesperson_id"]:
        return False
    return 0 < word_count(c["text"]) <= MAX_CARD_WORDS


def select_cards(candidates: list[dict]) -> list[dict]:
    """At most one valid card per salesperson. A card over 60 words is never emitted."""
    best: dict[str, dict] = {}
    ordered = sorted(candidates, key=lambda c: (-float(c.get("priority", 0)), c.get("lever", ""), c.get("salesperson_id", "")))
    for c in ordered:
        if not is_valid_card(c):
            continue
        best.setdefault(c["salesperson_id"], c)
    out = []
    for sp in sorted(best):
        c = best[sp]
        out.append(
            {
                "card_id": f"{c['store_id']}:{sp}:{c['lever']}",
                "store_id": c["store_id"],
                "salesperson_id": sp,
                "salesperson_name": c["salesperson_name"],
                "lever": c["lever"],
                "behaviour": c["behaviour"],
                "peer": {"salesperson_id": c["peer"]["salesperson_id"], "name": c["peer"]["name"]},
                "action": c["action"],
                "text": c["text"],
                "word_count": word_count(c["text"]),
                "checks": c["checks"],
            }
        )
        if c.get("definition"):  # how the quoted figure is defined; shown outside the 60 words
            out[-1]["definition"] = c["definition"]
    return out
