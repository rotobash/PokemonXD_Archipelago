"""ADDENDA 478-482 (2026-10-13).

478 -- (its purification count tests went with the heuristic tracker.)
479 -- no checks on Shadows that are only reachable after the goal.
480 -- the Poke Spots enter at the news point (0x37) and a watcher repairs a byte that falls below it.
481 -- SS Libra needs only the Phenac unlock (and the Scooter Upgrade when shuffled), not Phenac cleared.
482 -- a Death Link received outside battle whites the player out on the overworld.
"""
from __future__ import annotations

import random
import unittest
from unittest import mock

from .. import ram_client as rc

from . import PokemonXDTestBase  # noqa: E402
from .. import locations, species  # noqa: E402
from ..game_data import shadow_regions  # noqa: E402


class TestWhichShadowsArePostGoal(unittest.TestCase):
    def test_greevils_seven_and_the_dragonite(self) -> None:
        self.assertEqual(frozenset(range(73, 81)), shadow_regions.POST_GOAL_SHADOW_DDPKS)
        self.assertEqual(locations.POST_GOAL_VANILLA_SHADOW_COUNT, len(shadow_regions.POST_GOAL_SHADOW_DDPKS))
        for ddpk in range(73, 80):
            self.assertTrue(set(shadow_regions.shadow_carriers()[ddpk]) <= {199, 200})
        self.assertEqual(75, len(shadow_regions.shadow_regions_in_graph_order(include_post_goal=False)))
        self.assertEqual(83, len(shadow_regions.shadow_regions_in_graph_order()), "the census itself is unchanged")


class _PostGoal(PokemonXDTestBase):
    def _names(self):
        return {loc.name for loc in self.multiworld.get_locations(self.player)}


class TestNoChecksForThem(_PostGoal):
    options = {"shadow_pokemon_expansion": 0, "randomize_shadow_species": True}

    def test_no_purify_rung_past_the_pre_goal_shadows(self) -> None:
        # RETARGETED (per-species purifications): no `Purify - X` for a species only the post-goal Shadows carry.
        world = self.multiworld.worlds[self.player]
        names = self._names()
        self.assertEqual(75, sum(1 for name in names if name in locations.PURIFICATION_LOCATION_TO_DEX))
        self.assertEqual(75, world._purification_location_count)
        for dex in world._post_goal_only_dex:
            self.assertNotIn(locations.purification_location_name(dex), names, dex)

    def test_no_catch_for_a_species_only_they_carry(self) -> None:
        world = self.multiworld.worlds[self.player]
        self.assertTrue(world._post_goal_only_dex, "Greevil's seven are species of their own")
        names = self._names()
        for dex in world._post_goal_only_dex:
            self.assertNotIn(species.location_name_for_species(dex), names, dex)
        for dex, ddpks in world._shadow_catch_ddpks.items():
            self.assertFalse(set(ddpks) & shadow_regions.POST_GOAL_SHADOW_DDPKS, dex)

    def test_the_trainers_keep_their_shadows(self) -> None:
        """Nothing is taken off Greevil -- only the checks go."""
        world = self.multiworld.worlds[self.player]
        self.assertEqual(frozenset(), frozenset(world._shadow_removal_trainers))
        entries = world._shadow_species_assignment["entries"]
        from ..game_data.shadow_regions import ddpk_for_dpkm
        on_greevil = [e for e in entries if ddpk_for_dpkm().get(e["dpkm_index"]) in range(73, 80)]
        self.assertEqual(7, len(on_greevil))


class TestMovedOffGreevilTheyKeepTheirChecks(_PostGoal):
    options = {"shadow_pokemon_expansion": 0, "remove_greevil_shadows": True}

    def test_seven_more_rungs(self) -> None:
        world = self.multiworld.worlds[self.player]
        self.assertEqual(82, world._purification_location_count, "only the Dragonite is still post-goal")
        self.assertLessEqual(len(world._post_goal_only_dex), 1)


class TestShuffledLugiaNeverLandsWithoutChecks(_PostGoal):
    options = {"shuffle_shadow_lugia": True, "randomize_shadow_species": True}

    def test_lugia_has_its_checks(self) -> None:
        world = self.multiworld.worlds[self.player]
        self.assertIn(249, world._shadow_catch_labels)
        self.assertNotIn(249, world._post_goal_only_dex)
        self.assertIn(species.location_name_for_species(249), self._names())

    def test_the_exclusion_holds_for_every_draw(self) -> None:
        from ..game_data import shadow_legendaries as sl
        from ..game_data.shadow_regions import ddpk_for_dpkm
        post_goal = frozenset(d for d, ddpk in ddpk_for_dpkm().items() if ddpk in shadow_regions.POST_GOAL_SHADOW_DDPKS)

        class _Mon:
            def __init__(self, index, species_id):
                self.index, self.species_id = index, species_id

        for seed in range(200):
            mons = [_Mon(d, 1000 + d) for d in ddpk_for_dpkm()]
            home = next(m for m in mons if ddpk_for_dpkm()[m.index] == 73)
            home.species_id = sl.LUGIA_SPECIES_INDEX
            with mock.patch.object(sl, "_shadow_mons", return_value=mons), \
                    mock.patch.object(sl, "vanilla_lugia_index", return_value=home.index):
                landed = sl.place_shadow_lugia(None, {}, random.Random(seed), randomized=True,
                                               exclude_indices=post_goal)
            self.assertNotIn(landed, post_goal)


# --- 480 ------------------------------------------------------------------------------------------------------

from ..game_data import story_bytes as sb  # noqa: E402


class TestTheRockSpotGuard(unittest.TestCase):
    def test_still_entered_at_the_news_point(self) -> None:
        self.assertEqual(0x37, sb.area_entry_floor("Poke Spots"))

    def test_the_broken_window_is_repaired(self) -> None:
        for byte in (0x35, 0x36):
            bump = sb.live_bump_for("Poke Spots", byte, travel_shuffle=True, scooter_shuffle=False)
            self.assertIsNotNone(bump, hex(byte))
            self.assertEqual(0x37, bump.becomes)

    def test_never_touches_progress_past_it(self) -> None:
        for byte in (0x37, 0x38, 0x3B, 0x50):
            self.assertIsNone(sb.live_bump_for("Poke Spots", byte, travel_shuffle=True, scooter_shuffle=False))
        self.assertIsNone(sb.live_bump_for("Pyrite Town", 0x35, travel_shuffle=True, scooter_shuffle=False),
                          "only while standing at a spot")
        self.assertIsNone(sb.live_bump_for("Poke Spots", 0x35, travel_shuffle=False, scooter_shuffle=True),
                          "vanilla travel: the story plays as written")

    def test_the_bumper_writes_it_and_the_mark_follows(self) -> None:
        writes = []
        bumper = rc.LiveStoryByteBumper()
        with mock.patch.object(rc, "poke_story_byte", side_effect=lambda base, value: writes.append(value)):
            result = bumper.poll(0x80400000, "Poke Spots", 0x35, travel_shuffle=True, scooter_shuffle=False)
            self.assertEqual(0x37, result[0])
            self.assertIsNone(bumper.poll(0x80400000, "Poke Spots", 0x37, travel_shuffle=True,
                                          scooter_shuffle=False))
            # Something puts it back below the news later on -- even all the way to 0x35: repaired again.
            self.assertEqual(0x37, bumper.poll(0x80400000, "Poke Spots", 0x35, travel_shuffle=True,
                                               scooter_shuffle=False)[0])
            # A write that never lands (read straight back at 0x35) is still not fought every tick.
            self.assertIsNone(bumper.poll(0x80400000, "Poke Spots", 0x35, travel_shuffle=True,
                                          scooter_shuffle=False))
        self.assertEqual([0x37, 0x37], writes)
        self.assertEqual(1, bumper.declined_write_failed)
        memory = rc.AreaStoryByteMemory()
        memory.highest_by_region = {"Poke Spots": 0x35}
        self.assertEqual(0x37, memory.target_for("Poke Spots"))


# --- 481 ------------------------------------------------------------------------------------------------------

class TestSSLibraBehindThePhenacUnlock(PokemonXDTestBase):
    options = {"randomize_travel_locations": True, "key_item_shuffle": True, "shuffle_scooter_upgrade": True}

    def _reach(self, region):
        return self.multiworld.state.can_reach(region, player=self.player)

    def test_the_unlock_and_the_scooter_and_nothing_else(self) -> None:
        from .. import items
        self.collect_by_name(["Travel Unlock - SS Libra", "Travel Unlock - Phenac City"])
        self.assertTrue(self._reach("Phenac City"))
        self.assertFalse(self._reach("Phenac City (Post-Sixes)"), "Phenac is not cleared")
        self.assertFalse(self._reach("SS Libra"), "the Scooter Upgrade is shuffled")
        self.collect_by_name([items.SCOOTER_ITEM_NAME])
        self.assertTrue(self._reach("SS Libra"))

    def test_not_without_phenac(self) -> None:
        from .. import items
        self.collect_by_name(["Travel Unlock - SS Libra", items.SCOOTER_ITEM_NAME])
        self.assertFalse(self._reach("SS Libra"))


if __name__ == "__main__":
    unittest.main()
