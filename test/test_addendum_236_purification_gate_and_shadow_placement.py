"""ADDENDUM 236. Two live bugs, two fixes.

Shadow purification checks were sending at the wrong times, including in battle. And rematching Resix and the
like respawned their shadow Pokemon even after it had been caught, which allowed infinite catches on rematches.
"""
from __future__ import annotations

import random
import unittest

from .. import ram_client
from ..game_data import census_repeat_column, missable_trainers
from ..game_data.real_trainer_data import real_species_pool, real_trainer_free_slot_census
from ..randomizer.shadow_expansion import build_shadow_expansion_plans


class TestShadowExpansionPlacement(unittest.TestCase):
    """A generated Shadow is a catch LOCATION, so its trainer must be fightable exactly once."""

    def setUp(self) -> None:
        self.census = real_trainer_free_slot_census()
        self.pool = real_species_pool()
        if not self.census or not self.pool:
            self.skipTest("real ISO census data isn't present in this build")
        self.excluded = missable_trainers.shadow_expansion_excluded_trainer_indices()
        self.refightable = {
            index for index, (repeat, _missable) in census_repeat_column.CENSUS_REPEAT_AND_MISSABLE.items()
            if repeat == "final"
        }

    def _plan(self, seed: int):
        return build_shadow_expansion_plans(
            self.census, self.pool, {}, excluded_species=set(), target_count=60,
            rng=random.Random(seed), excluded_trainer_indices=self.excluded,
        )

    def test_no_generated_shadow_lands_on_a_refightable_trainer(self) -> None:
        """The reported bug: the game lets you re-fight a `final` trainer, so its Shadow can be snagged again
        and again. ADDENDUM 466: ADDENDUM 465 stopped the engine rebuilding a snagged Shadow, so the four regioned,
        safe `final` rows (`REFIGHTABLE_FINAL_SHADOW_HOSTS`) may host one now; every other `final` row may not."""
        allowed = missable_trainers.REFIGHTABLE_FINAL_SHADOW_HOSTS
        for seed in (3, 11, 42, 101):
            targets = {plan["trainer_index"] for plan in self._plan(seed)}
            self.assertEqual(set(), targets & (self.refightable - allowed), f"seed {seed}")

    def test_no_generated_shadow_lands_on_a_missable_trainer(self) -> None:
        """Found in the same pass: a Shadow on a missable fight is a catch that can be lost for the seed."""
        for seed in (3, 11, 42, 101):
            targets = {plan["trainer_index"] for plan in self._plan(seed)}
            self.assertEqual(set(), targets & missable_trainers.MISSABLE_TRAINER_INDICES, f"seed {seed}")

    def test_the_exclusion_does_not_starve_the_setting(self) -> None:
        """The ceiling is 44; there must still be room for all of them."""
        for seed in (3, 11, 42):
            placed = sum(len(plan["new_pokemon"]) for plan in self._plan(seed))
            self.assertEqual(44, placed, f"seed {seed} placed {placed} Shadows")

    def test_the_refightable_rows_were_already_inside_the_filler_only_set(self) -> None:
        """Why this is an existing fence applied, not a new one invented."""
        self.assertTrue(self.refightable)
        self.assertTrue(self.refightable - missable_trainers.REFIGHTABLE_FINAL_SHADOW_HOSTS <= self.excluded)   # 466
        self.assertTrue(self.refightable <= missable_trainers.FILLER_ONLY_TRAINER_INDICES
                        | missable_trainers.MANDATORY_REMATCH_INDICES)


class TestTheTwoSpeciesKeysAreInterchangeable(unittest.TestCase):
    """ADDENDUM 220's ledger is persisted and keyed by whatever this tracker calls a species. Falling back to
    `national_dex` is only safe if it lands in the same namespace as the name lookup it replaces."""

    def test_every_live_species_resolves_the_same_both_ways(self) -> None:
        from ..tools import xd_species_index as xi
        agree = disagree = 0
        for live in range(1, 1000):
            dex = xi.national_dex_for_live_species(live)
            name = xi.name_for_live_species(live)
            if dex is None or not name:
                continue
            by_name = ram_client.species_dex_from_name(name)
            if by_name is None:
                continue
            if by_name == dex:
                agree += 1
            else:
                disagree += 1
        self.assertGreater(agree, 300, "the species index should resolve most of the dex")
        self.assertEqual(0, disagree, "the two species keys disagree -- the persisted ledger would be re-keyed")

    def test_the_raw_field_is_NOT_in_that_namespace(self) -> None:
        """Why the old fallback was wrong: past the live-index gap the raw value is its own numbering, and
        for most values it is simply not the dex number. Found by scanning rather than by picking one, since
        the two do coincide at some values by arithmetic accident."""
        from ..tools import xd_species_index as xi
        differing = [
            live for live in range(xi.LIVE_INDEX_GAP_START, xi.LIVE_INDEX_GAP_START + 200)
            if xi.national_dex_for_live_species(live) not in (None, live)
        ]
        self.assertTrue(differing, "expected the live numbering to diverge from the dex past the gap")


class TestTheTrainerIndexNamespacesLineUp(unittest.TestCase):
    """The whole re-fightable fence rests on the workbook's Repeat? column being keyed by the SAME index as
    the DTNR-derived census. If they were different namespaces the fence would exclude the wrong trainers --
    worse than doing nothing."""

    def test_the_roster_and_the_repeat_column_cover_the_same_indices(self) -> None:
        from ..game_data import trainer_roster
        self.assertEqual(set(trainer_roster.TRAINERS_BY_INDEX),
                         set(census_repeat_column.CENSUS_REPEAT_AND_MISSABLE))

    def test_the_roster_carries_real_dtnr_team_data(self) -> None:
        """Which is what makes it the same namespace as the free-slot census, not a parallel list."""
        # ADDENDUM 250: was an absolute `__import__("pokemon_xd.game_data.trainer_roster", ...)`, which
        # double-registers the world under the ordinary worlds/ layout and made this test error instead of
        # run.
        from ..game_data import trainer_roster

        first = trainer_roster.TRAINERS_BY_INDEX[1]
        self.assertEqual("HORDEL", first["name"])
        self.assertTrue(first["team"], "roster entries must carry the trainer's real team")

