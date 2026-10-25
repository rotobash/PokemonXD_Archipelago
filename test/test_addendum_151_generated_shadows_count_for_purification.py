"""ADDENDUM 151 (2026-09-11): generated Shadow Pokemon and the purification checks.

Every generated Shadow Pokemon is included in the purification checks, and by construction rather than by accident -- but the reasons are spread across three modules and
none of them were asserted anywhere, so a future change to any one of them could break it silently. These
tests pin the chain:

  1. `shadow_expansion` draws every new species with `rng.sample` from a pool that already excludes the 83
     vanilla shadow species -- so no generated shadow ever shares a species with another shadow, new or old.
  2. All 83 vanilla shadow species are themselves distinct.
  3. Purification checks are "Purify - {species}", one per species, so two Shadows sharing a species would be one
     check. Nothing in this game produces that, and these tests are what keep it that way.

Also here: a drift fix. `ram_client.CHEST_LOCATION_COUNT` still said 115 after ADDENDUM 134 dropped
locations.py's to 91.
"""
from __future__ import annotations

import json
import pathlib
import random
import unittest

from .. import locations, ram_client as rc
from ..game_data import real_trainer_data as rtd
from ..game_data.real_moveset_data import load_level_up_moves
from ..game_data.real_shadow_data import vanilla_shadow_species
from ..randomizer import shadow_expansion

_SHADOW_LIST = pathlib.Path(__file__).resolve().parent.parent / "data" / "shadow_pokemon_list.json"
class TestMirroredConstantsDoNotDrift(unittest.TestCase):
    """ram_client.py duplicates these rather than importing locations.py (which needs the real Archipelago
    package to load). Duplication is fine; silent drift is not."""

    def test_chest_count_matches_locations(self) -> None:
        self.assertEqual(rc.CHEST_LOCATION_COUNT, locations.CHEST_LOCATION_COUNT)

    def test_chest_count_is_the_post_key_item_fence_number(self) -> None:
        """ADDENDUM 134 dropped it 115 -> 91; ram_client kept saying 115 until ADDENDUM 151.

        RETARGETED 2026-09-13 (ADDENDUM 168): 91 -> 90. Chest 115 sits in room 175, the debug room that
        game_data/chest_regions.EXCLUDED_ROOMS now drops outright, and it was never covered by the key-item
        fence (its item id is 0). The literal is kept deliberately -- this test's whole job is to be a second,
        independent copy of the number so ram_client.py's hand-mirrored constant cannot drift in silence, which
        is exactly what happened between ADDENDUM 134 and 151.
        """
        # ADDENDUM 174: 90 -> 89. The literal is still kept deliberately (this test's whole job is to be a
        # second, independent copy of the number), but it now counts chest LOCATIONS, and chests 108/113 share
        # one. CHEST_COVERED_CHEST_COUNT is still 90.
        # ADDENDUM 177: 89 -> 94 and 90 -> 95. Five fenced key-item chests became checks under KeyItemShuffle.
        # UPDATED 2026-09-15 (ADDENDUM 224): 95, not 94. The 108/113 shared-flag pair was split back into two
        # locations -- identity comes from the chest's own berry now, not from the flag they share.
        # 94: chest 113 is a non-item box sharing 108's flag (chest_regions.NON_ITEM_CHESTS), not a location.
        self.assertEqual(rc.CHEST_LOCATION_COUNT, 94)
        self.assertEqual(locations.CHEST_COVERED_CHEST_COUNT, 94)

    def test_the_client_can_never_name_a_location_the_seed_does_not_have(self) -> None:
        for name in rc.CHEST_LOCATION_NAMES:
            self.assertIn(name, locations.LOCATION_TABLE)
        # ADDENDUM 174: the two tables are built independently (ram_client cannot import locations), so the
        # name FORMAT is the duplicated part and a one-character difference would make every chest check bounce.
        self.assertEqual(rc.CHEST_ID_TO_LOCATION, locations.CHEST_ID_TO_LOCATION)
        # RETARGETED (per-species purifications): the client names purifications with locations.py's own
        # `purification_location_name`, by the species main.dol's Shadow list gives the purified id.
        client = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        self.assertIn("name = purification_location_name(dex)", client)
        self.assertNotIn("rc.purification_location_name", client)
        self.assertNotIn("ram_client.purification_location_name", client)
        for dex in range(1, 387):
            self.assertIn(locations.purification_location_name(dex), locations.LOCATION_TABLE)


class TestSpeciesUniqueness(unittest.TestCase):
    def test_the_83_vanilla_shadows_are_all_different_species(self) -> None:
        entries = json.loads(_SHADOW_LIST.read_text())
        names = [e["species_name"] for e in entries]
        self.assertEqual(len(names), 83)
        self.assertEqual(len(set(names)), 83, "a repeated species would count as one purification, not two")

    def test_generated_shadows_never_reuse_a_species(self) -> None:
        census = rtd.real_trainer_free_slot_census()
        species_pool = rtd.real_species_pool()
        level_up_moves = load_level_up_moves()
        excluded = vanilla_shadow_species()
        if not (census and species_pool and level_up_moves and excluded is not None):
            self.skipTest("real ISO-extracted data files not present in this build")
        for seed in (1, 7, 99):
            plans = shadow_expansion.build_shadow_expansion_plans(
                census, species_pool, level_up_moves, excluded,
                shadow_expansion.SHADOW_EXPANSION_MAX_NEW_POKEMON, random.Random(seed),
            )
            generated = [p["species"] for plan in plans for p in plan["new_pokemon"]]
            self.assertTrue(generated)
            self.assertEqual(len(generated), len(set(generated)), f"seed {seed} repeated a species")

    def test_generated_shadows_never_collide_with_a_vanilla_shadow(self) -> None:
        census = rtd.real_trainer_free_slot_census()
        species_pool = rtd.real_species_pool()
        level_up_moves = load_level_up_moves()
        excluded = vanilla_shadow_species()
        if not (census and species_pool and level_up_moves and excluded is not None):
            self.skipTest("real ISO-extracted data files not present in this build")
        plans = shadow_expansion.build_shadow_expansion_plans(
            census, species_pool, level_up_moves, excluded,
            shadow_expansion.SHADOW_EXPANSION_MAX_NEW_POKEMON, random.Random(4),
        )
        generated = {p["species"] for plan in plans for p in plan["new_pokemon"]}
        self.assertFalse(generated & set(excluded))


# ============================================================================================================
# The tracker itself, driven with a synthetic party
# ============================================================================================================
if __name__ == "__main__":
    unittest.main()
