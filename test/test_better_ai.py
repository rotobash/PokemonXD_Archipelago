"""Better AI: each listed story trainer's DTNR +0x28 AI row becomes `GREEVIL_AI_INDEX`, or
`GREEVIL_SHADOW_AI_INDEX` when its team has a shadow Pokemon."""

from __future__ import annotations

import unittest

from ..tools import iso_patcher
from ..tools import xd_deck_format as deck_format
from .test_addendum_423_nightmare_citadark import _deck

AI = iso_patcher.GREEVIL_AI_INDEX
SHADOW_AI = iso_patcher.GREEVIL_SHADOW_AI_INDEX


def _story() -> bytes:
    trainers = {i: {"ai": i, "slots": [1]} for i in range(1, 6)}
    trainers[4]["mask"] = 0b1  # trainer 4's slot 0 is a shadow Pokemon
    return _deck(trainers, [bytes(0x20)] * 2, [bytes(0x20)] * (SHADOW_AI + 1))


def _edit(story: bytes, vanilla: "dict[int, int]", skip=frozenset(), ai: int = AI) -> "tuple[bytes, list[int]]":
    return iso_patcher.apply_better_ai_edit(story, vanilla, ai, SHADOW_AI, skip)


class TestTheEdit(unittest.TestCase):
    def test_listed_trainers_take_the_row(self) -> None:
        out, changed = _edit(_story(), {1: 1, 2: 2, 3: 3})
        deck = deck_format.DeckFile(out)
        self.assertEqual([1, 2, 3], changed)
        self.assertEqual([AI] * 3 + [4, 5], [deck.trainer(i)["ai_index"] for i in range(1, 6)])

    def test_shadow_trainers_take_the_shadow_row(self) -> None:
        out, changed = _edit(_story(), {3: 3, 4: 4})
        deck = deck_format.DeckFile(out)
        self.assertEqual([3, 4], changed)
        self.assertEqual([AI, SHADOW_AI], [deck.trainer(i)["ai_index"] for i in (3, 4)])

    def test_skipped_trainers_keep_theirs(self) -> None:
        out, changed = _edit(_story(), {1: 1, 2: 2}, {2})
        self.assertEqual([1], changed)
        self.assertEqual(2, deck_format.DeckFile(out).trainer(2)["ai_index"])

    def test_already_patched_changes_nothing(self) -> None:
        once, _ = _edit(_story(), {1: 1, 4: 4})
        twice, changed = _edit(once, {1: 1, 4: 4})
        self.assertEqual([], changed)
        self.assertEqual(once, twice)

    def test_a_different_disc_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            _edit(_story(), {1: 9})

    def test_a_row_past_the_table_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            _edit(_story(), {1: 1}, ai=999)

    def test_the_shipped_extraction_is_read(self) -> None:
        vanilla = iso_patcher._vanilla_ai_index_by_trainer()
        self.assertEqual(232, len(vanilla))
        self.assertEqual(AI, vanilla[AI])
        self.assertEqual(SHADOW_AI, vanilla[SHADOW_AI])
