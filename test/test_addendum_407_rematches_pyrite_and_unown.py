"""ADDENDUM 407 (2026-10-03) -- mandatory rematches can hold items, Pyrite is one level tier, the Unown PID watch.

Mandatory rematches can hold progression/useful items. Pyrite visits 1 and 2 share one level-scaling tier rather
than being separated. (The Unown PID watch went with the heuristic purification tracker -- purifications come from
the AP patch's log by Shadow id now.)
"""
from __future__ import annotations

import unittest

from BaseClasses import LocationProgressType

from . import PokemonXDTestBase
from .. import ram_client as rc
from ..game_data import missable_trainers as mt, trainer_roster as tr
from ..randomizer import path_level_scaling as pls

ON = ["Defeat - Naps #2"]
# Cida #2 and the Sixes' #2 are filler-only; Naps #2 is the only one that changed.
# ADDENDUM 409: six of the original ten are no longer locations at all -- the rematches of Cida, Clerr, Belish, Dosk,
# Hebon, Aferd, Finol, Dert, Raling, Labet and Doby are removed, and, for the Sixes, all their other fights
# (Browsix #4). The Sixes' #2 stays (at Phenac, missable, behind the disc and the note) and is still filler-only;
# Laken and Zook are not part of that trim.
HELD = ["Defeat - Resix #2", "Defeat - Greesix #2", "Defeat - Laken #3"]   # ADDENDUM 436: Zook #2 is not a check
RULED_OUT = ["Defeat - Cida #2", "Defeat - Aferd #2", "Defeat - Hebon #2", "Defeat - Browsix #4",
             "Defeat - Dosk #2", "Defeat - Finol #2"]


class TestTheAllowlist(unittest.TestCase):
    def test_only_naps_two(self) -> None:
        names = {tr.trainer_label(tr.TRAINERS_BY_INDEX[i]) for i in mt.MANDATORY_REMATCH_INDICES}
        self.assertEqual(set(ON), names)

    def test_the_progression_fence_is_the_old_one_minus_them(self) -> None:
        self.assertEqual(mt.FILLER_ONLY_TRAINER_INDICES, mt.UNREDOABLE_TRAINER_INDICES - mt.MANDATORY_REMATCH_INDICES)

    def test_shadow_expansion_may_use_them_now(self) -> None:
        """A Shadow on a re-fightable fight WAS the infinite catch (ADDENDUM 236); ADDENDUM 465 stopped the engine
        rebuilding a snagged Shadow, and ADDENDUM 466 lets Naps #2 host one."""
        self.assertFalse(mt.MANDATORY_REMATCH_INDICES & mt.shadow_expansion_excluded_trainer_indices())
        self.assertTrue(mt.MANDATORY_REMATCH_INDICES <= mt.REFIGHTABLE_FINAL_SHADOW_HOSTS)


class TestInAGeneratedWorld(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "key_item_shuffle": True}

    def test_the_eight_can_hold_progression(self) -> None:
        for name in ON:
            self.assertEqual(LocationProgressType.DEFAULT,
                             self.multiworld.get_location(name, self.player).progress_type, name)

    def test_the_held_back_ones_are_not_locations(self) -> None:
        # Numbered rematch checks are removed for every repeated trainer outside the forced second fights, so
        # the held-back rematches no longer exist to hold anything.
        created = {location.name for location in self.multiworld.get_locations(self.player)}
        for name in HELD:
            self.assertIn(name, tr.NUMBERED_REMATCH_DEFEAT_LOCATIONS, name)
            self.assertNotIn(name, created, name)

    def test_the_ruled_out_ones_are_not_locations(self) -> None:
        # ADDENDUM 409: these checks were removed by name; they cannot hold anything because they do not exist.
        created = {location.name for location in self.multiworld.get_locations(self.player)}
        for name in RULED_OUT:
            self.assertIn(name, tr.RULED_OUT_DEFEAT_LOCATIONS, name)
            self.assertNotIn(name, created, name)

    def test_naps_two_still_needs_the_id_card(self) -> None:
        from BaseClasses import CollectionState

        state = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.player == self.player and item.name != "Data ROM & ID Card":
                state.collect(item, True)
        state.sweep_for_advancements()
        self.assertFalse(self.multiworld.get_location("Defeat - Naps #2", self.player).can_reach(state))


class TestPyriteIsOneTier(unittest.TestCase):
    def test_both_visits_share_a_rung(self) -> None:
        known = set(pls.region_by_trainer_index().values())
        tiers = pls.path_tiers(known)
        self.assertEqual(pls.tier_index("Pyrite Town", tiers, known),
                         pls.tier_index("Pyrite Town (ONBS)", tiers, known))
        self.assertEqual(12, len(tiers))

    def test_every_pyrite_fight_gets_one_level(self) -> None:
        levels = pls.level_by_trainer_index()
        regions = pls.region_by_trainer_index()
        pyrite = {levels[i] for i, region in regions.items()
                  if region in ("Pyrite Town", "Pyrite Town (ONBS)") and i in levels}
        self.assertEqual(1, len(pyrite), pyrite)


if __name__ == "__main__":
    unittest.main()


class TestMisfiledItems(unittest.TestCase):
    """ADDENDUM 408: the "No256 in the TMs tab" symptom. Detection only -- it names what is where."""

    def _bag(self, shared: "dict[int, tuple[int, int]]", items: "dict[int, tuple[int, int]]"):
        def fake_read(base, count):
            table = shared if base == 0x1000 + rc.POKEBALL_POCKET_OFFSET else items
            return [rc.BagSlot(i, base + i * 4, *table.get(i, (0, 0))) for i in range(count)]
        return fake_read

    def test_a_healing_item_in_the_tm_tab_is_named(self) -> None:
        from unittest import mock

        shared = {16: (289, 1), 23: (19, 1), 85: (150, 2)}      # TM01, Full Restore in the TM tab, a berry
        with mock.patch.object(rc, "read_pocket", self._bag(shared, {0: (13, 5)})):
            found = rc.find_misfiled_items(0x1000)
        self.assertEqual([("TMs", 7, 19, 1)], found)

    def test_a_tm_in_the_items_pocket_is_named(self) -> None:
        from unittest import mock

        with mock.patch.object(rc, "read_pocket", self._bag({}, {3: (300, 1)})):
            self.assertEqual([("Items", 3, 300, 1)], rc.find_misfiled_items(0x1000))

    def test_a_clean_bag_says_nothing(self) -> None:
        from unittest import mock

        with mock.patch.object(rc, "read_pocket", self._bag({0: (4, 10), 20: (300, 1), 90: (160, 1)},
                                                            {0: (19, 2)})):
            self.assertEqual([], rc.find_misfiled_items(0x1000))
