"""Purification Unlocks, and the per-species "Purify - X" checks they open.

One "Purification Unlock - {species}" per Shadow species in the seed. The client writes every Shadow id of every
received unlock's species into the AP patch's `give.purified` list, and with `AP_ENABLE_PURIFYCHECKS` set the patch
refuses to purify a Shadow that is not on it. The first progression unlock is for a Shadow snaggable from the start
and is placed early; `purification_progression_cap` picks the rest; the others are useful, post-goal ones filler.
"""
from __future__ import annotations

import asyncio
import struct
import unittest
from types import SimpleNamespace
from unittest import mock

from BaseClasses import CollectionState, ItemClassification, LocationProgressType

from . import PokemonXDTestBase
from .. import Client, ap_patch as ap, items, locations as L, options as O, ram_client as rc, rules
from ..game_data.shadow_engine import VANILLA_DARK_POKEMON_LIST
from ..tools.xd_species_index import national_dex_for

TEDDIURSA = 216


class TestTheGiveLayoutIsTheCStruct(unittest.TestCase):
    """`GiveAPItems` holds a pointer (`ClientPokemonGetParam.NameId`), so it is 4-aligned after the 0x78A-byte
    `CheckedAPItems` at +0x004; each `ClientPokemonGetParam` is 16 bytes."""

    def test_the_offsets(self):
        self.assertEqual(0x790, ap.GIVE_OFFSET)
        self.assertEqual(0xF94, ap.GIVE_PURIFY_COUNTER_OFFSET)
        self.assertEqual(0xF96, ap.GIVE_PURIFIED_OFFSET)
        self.assertEqual(2 + 2 * 128, ap.GIVE_PURIFY_READ_SIZE)

    def test_the_flag_follows_the_option(self):
        self.assertEqual(ap.FLAG_PURIFY_CHECKS, ap.feature_flags(item_checks=False, pokemon_checks=False,
                                                                purify_checks=True, death_link=False))


class TestTheGiveList(unittest.TestCase):
    def test_pack_and_parse_round_trip(self):
        packed = ap.pack_give_purified([5, 1, 90])
        self.assertEqual(struct.pack(">HHHH", 3, 5, 1, 90), packed)
        raw = packed + bytes(ap.GIVE_PURIFY_READ_SIZE - len(packed))
        self.assertEqual((5, 1, 90), ap.parse_give_purified(raw))

    def test_a_counter_past_the_array_is_not_the_list(self):
        raw = struct.pack(">H", 129) + bytes(ap.GIVE_PURIFY_READ_SIZE - 2)
        self.assertIsNone(ap.parse_give_purified(raw))

    def test_the_entries_are_written_before_the_counter(self):
        writes = []
        with mock.patch.object(ap, "AP_BLOCK_ADDRESS", 0), \
                mock.patch.object(rc, "write_bytes", side_effect=lambda address, data: writes.append((address, data))):
            ap.write_give_purified([7, 8])
        self.assertEqual([(ap.GIVE_PURIFIED_OFFSET, struct.pack(">HH", 7, 8)),
                          (ap.GIVE_PURIFY_COUNTER_OFFSET, struct.pack(">H", 2))], writes)

    def test_an_empty_list_writes_only_the_counter(self):
        writes = []
        with mock.patch.object(rc, "write_bytes", side_effect=lambda address, data: writes.append((address, data))):
            ap.write_give_purified([])
        self.assertEqual([(ap.AP_BLOCK_ADDRESS + ap.GIVE_PURIFY_COUNTER_OFFSET, b"\x00\x00")], writes)


class TestTheShadowList(unittest.TestCase):
    def _raw(self, listing):
        return struct.pack(f">{len(listing)}H", *listing)

    def test_the_vanilla_list_reads(self):
        listing = ap.parse_dark_pokemon_list(self._raw(VANILLA_DARK_POKEMON_LIST))
        self.assertEqual(VANILLA_DARK_POKEMON_LIST, listing)
        by_dex = ap.shadow_ids_by_dex(listing)
        self.assertEqual((1,), by_dex[TEDDIURSA])   # the intro's Shadow is id 1

    def test_an_unloaded_dol_does_not_read_as_the_list(self):
        self.assertIsNone(ap.parse_dark_pokemon_list(bytes(256)))
        self.assertIsNone(ap.parse_dark_pokemon_list(self._raw(VANILLA_DARK_POKEMON_LIST)[:100]))

    def test_id_zero_is_never_a_shadow(self):
        listing = list(VANILLA_DARK_POKEMON_LIST)
        self.assertNotIn(0, {i for ids in ap.shadow_ids_by_dex(listing).values() for i in ids})


class TestTheOption(unittest.TestCase):
    def test_it_is_off_by_default_and_sits_after_the_cap(self):
        self.assertFalse(O.PurificationUnlocks.default)
        names = list(O.PokemonXDOptions.type_hints)
        self.assertEqual(names.index("purification_progression_cap") + 1, names.index("purification_unlocks"))


class TestTheItemTable(unittest.TestCase):
    def test_one_per_species_frozen_in_dex_order(self):
        self.assertEqual(386, len(items.PURIFICATION_UNLOCK_ITEMS))
        self.assertEqual(262, items.ITEM_TABLE["Purification Unlock - Bulbasaur"].id_offset)
        self.assertEqual(262 + TEDDIURSA - 1, items.ITEM_TABLE["Purification Unlock - Teddiursa"].id_offset)
        self.assertEqual(647, items.ITEM_TABLE["Purification Unlock - Deoxys"].id_offset)

    def test_no_pool_pass_draws_one_on_its_own(self):
        for name in items.PURIFICATION_UNLOCK_ITEMS:
            self.assertNotIn(name, items.FILLER_ITEMS)
            self.assertNotIn(name, items.USEFUL_ITEMS)
            self.assertEqual(ItemClassification.filler, items.ITEM_TABLE[name].classification)

    def test_they_are_a_group(self):
        self.assertEqual(set(items.PURIFICATION_UNLOCK_ITEMS), items.ITEM_NAME_GROUPS["Purification Unlocks"])


class _Unlocks(PokemonXDTestBase):
    options = {"purification_unlocks": True, "purification_progression_cap": 10, "randomize_shadow_species": True,
               "shadow_pokemon_expansion": 10}

    def unlocks_in_pool(self) -> "dict[str, ItemClassification]":
        return {item.name: item.classification for item in self.multiworld.itempool
                if item.player == self.player and item.name in items.PURIFICATION_UNLOCK_NAME_TO_DEX}


class TestUnlocksOn(_Unlocks):
    def test_one_unlock_per_shadow_species(self):
        pool = self.unlocks_in_pool()
        self.assertEqual({items.purification_unlock_item_name(dex) for dex in self.world._shadow_species_dex},
                         set(pool))

    def test_the_cap_decides_which_are_progression(self):
        pool = self.unlocks_in_pool()
        progression = {name for name, cls in pool.items() if cls & ItemClassification.progression}
        self.assertEqual({items.purification_unlock_item_name(dex) for dex in self.world._purification_progression_dex},
                         progression)
        self.assertEqual(10, len(progression))

    def test_the_rest_are_useful_and_the_post_goal_ones_filler(self):
        for name, cls in self.unlocks_in_pool().items():
            dex = items.PURIFICATION_UNLOCK_NAME_TO_DEX[name]
            if dex in self.world._purification_unlock_progression_dex:
                continue
            expected = (ItemClassification.useful if dex in self.world._purifiable_shadow_dex
                        else ItemClassification.filler)
            self.assertEqual(expected, cls, name)

    def test_the_first_is_snaggable_from_the_start_and_placed_early(self):
        first = self.world._purification_progression_dex[0]
        self.assertTrue(rules.purification_way_is_open(CollectionState(self.multiworld), self.player,
                                                       self.world._purification_gates[first]))
        self.assertEqual({items.purification_unlock_item_name(first): 1},
                         self.multiworld.local_early_items[self.player])

    def test_a_progression_purification_needs_its_unlock(self):
        dex = self.world._purification_progression_dex[0]
        unlock = items.purification_unlock_item_name(dex)
        location = self.multiworld.get_location(L.purification_location_name(dex), self.player)
        self.assertEqual(LocationProgressType.DEFAULT, location.progress_type)
        state = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.player == self.player and item.advancement and item.name != unlock:
                state.collect(item, True)
        self.assertFalse(location.can_reach(state))
        state.collect(self.world.create_item(unlock), True)
        self.assertTrue(location.can_reach(state))

    def test_every_other_purification_is_filler_only(self):
        picked = set(self.world._purification_progression_dex)
        for location in self.multiworld.get_locations(self.player):
            dex = L.PURIFICATION_LOCATION_TO_DEX.get(location.name)
            if dex is not None and dex not in picked:
                self.assertEqual(LocationProgressType.EXCLUDED, location.progress_type, location.name)

    def test_create_item_carries_the_seeds_classification(self):
        dex = self.world._purification_progression_dex[0]
        self.assertTrue(self.world.create_item(items.purification_unlock_item_name(dex)).advancement)

    def test_the_client_is_told(self):
        self.assertTrue(self.world.fill_slot_data()["purification_unlocks"])


class TestUnlocksOnWithCapZero(_Unlocks):
    options = dict(_Unlocks.options, purification_progression_cap=0)

    def test_the_first_unlock_is_still_progression(self):
        progression = [name for name, cls in self.unlocks_in_pool().items() if cls & ItemClassification.progression]
        self.assertEqual(1, len(progression))
        self.assertEqual(1, sum(self.multiworld.local_early_items[self.player].values()))

    def test_but_no_purification_holds_progression(self):
        for location in self.multiworld.get_locations(self.player):
            if location.name in L.PURIFICATION_LOCATION_TO_DEX:
                self.assertEqual(LocationProgressType.EXCLUDED, location.progress_type, location.name)


class TestUnlocksOff(PokemonXDTestBase):
    options = {"purification_unlocks": False, "purification_progression_cap": 10}

    def test_no_unlocks_and_no_rule_on_them(self):
        self.assertFalse([item for item in self.multiworld.itempool
                          if item.name in items.PURIFICATION_UNLOCK_NAME_TO_DEX])
        self.assertEqual({}, self.multiworld.local_early_items[self.player])
        world = self.multiworld.worlds[self.player]
        self.assertEqual(set(), world._purification_unlock_progression_dex)
        self.assertEqual(10, len(world._purification_progression_dex))


# --- the client ---------------------------------------------------------------------------------------------------

def _unlock(dex: int):
    return SimpleNamespace(item=Client.ITEM_NAME_TO_ID[items.purification_unlock_item_name(dex)])


def _ctx(**fields):
    base = dict(purification_unlocks=True, purification_checks=True, items_received=[],
                shadow_ids_by_dex={}, shadow_dex_by_id={}, purification_unlock_ids_written=None,
                ap_patch_block=None, block_base=None, _shadow_monitor_purified_last=set(),
                purified_shadow_ids=set(), checked_locations=set(), server_locations=set(),
                missing_locations=set(), verbose_logging=False)
    base.update(fields)
    return SimpleNamespace(**base)


class TestTheClientWritesTheUnlocks(unittest.TestCase):
    def _sync(self, ctx, current):
        writes = []
        with mock.patch.object(ap, "read_give_purified", return_value=current), \
                mock.patch.object(ap, "write_give_purified", side_effect=writes.append):
            Client.sync_purification_unlocks(ctx)
        return writes

    def test_every_shadow_id_of_each_received_species(self):
        ctx = _ctx(items_received=[_unlock(TEDDIURSA), _unlock(37)],
                   shadow_ids_by_dex={TEDDIURSA: (1,), 37: (2, 90), 100: (29,)})
        self.assertEqual([(1, 2, 90)], self._sync(ctx, ()))

    def test_nothing_is_written_while_the_game_already_has_it(self):
        ctx = _ctx(items_received=[_unlock(TEDDIURSA)], shadow_ids_by_dex={TEDDIURSA: (1,)})
        self.assertEqual([], self._sync(ctx, (1,)))

    def test_a_cold_boot_is_rewritten(self):
        """A power cycle empties the block; the next poll puts the whole received set back."""
        ctx = _ctx(items_received=[_unlock(TEDDIURSA), _unlock(37)],
                   shadow_ids_by_dex={TEDDIURSA: (1,), 37: (2,)})
        self.assertEqual([(1, 2)], self._sync(ctx, ()))
        self.assertEqual([(1, 2)], self._sync(ctx, None))   # garbage counter -- not the patch's list yet

    def test_a_vanilla_list_in_a_randomized_seed_is_reported_once(self):
        raw = struct.pack(f">{len(VANILLA_DARK_POKEMON_LIST)}H", *VANILLA_DARK_POKEMON_LIST)
        ctx = _ctx(randomize_shadow_species=True, _shadow_list_warned=False)
        with mock.patch.object(rc, "read_bytes", return_value=raw),                 mock.patch.object(Client.logger, "warning") as warned:
            Client.refresh_shadow_ids(ctx)
            Client.refresh_shadow_ids(ctx)
        self.assertEqual(1, warned.call_count)
        self.assertEqual((1,), ctx.shadow_ids_by_dex[TEDDIURSA])

    def test_off_never_touches_the_list(self):
        ctx = _ctx(purification_unlocks=False, items_received=[_unlock(TEDDIURSA)],
                   shadow_ids_by_dex={TEDDIURSA: (1,)})
        self.assertEqual([], self._sync(ctx, ()))


class TestTheClientSendsPurifications(unittest.TestCase):
    def _check(self, ctx, monitor=None):
        sent = []

        async def fake_send(_ctx, names):
            sent.extend(names)

        with mock.patch.object(Client, "_send_checks", side_effect=fake_send), \
                mock.patch.object(Client.ram_client, "read_shadow_monitor", return_value=monitor):
            asyncio.run(Client.check_purifications(ctx))
        return sent

    def test_the_patch_log_names_the_species_this_seed_gave_the_id(self):
        block = SimpleNamespace(purified=(1,))
        ctx = _ctx(ap_patch_block=block, shadow_dex_by_id={1: 155})   # id 1 randomized into a Cyndaquil
        self.assertEqual(["Purify - Cyndaquil"], self._check(ctx))

    def test_the_shadow_monitor_needs_two_agreeing_reads(self):
        ctx = _ctx(block_base=0x80000000, shadow_dex_by_id={1: TEDDIURSA})
        self.assertEqual([], self._check(ctx, monitor={1}))
        self.assertEqual(["Purify - Teddiursa"], self._check(ctx, monitor={1}))

    def test_a_location_outside_the_seed_is_not_offered(self):
        block = SimpleNamespace(purified=(1,))
        ctx = _ctx(ap_patch_block=block, shadow_dex_by_id={1: TEDDIURSA},
                   server_locations={Client.LOCATION_NAME_TO_ID["Purify - Cyndaquil"]})
        self.assertEqual([], self._check(ctx))

    def test_off_sends_nothing(self):
        ctx = _ctx(purification_checks=False, ap_patch_block=SimpleNamespace(purified=(1,)),
                   shadow_dex_by_id={1: TEDDIURSA})
        self.assertEqual([], self._check(ctx))


class TestTheVanillaListAgreesWithTheCensus(unittest.TestCase):
    def test_vanilla_shadow_ids_resolve_to_their_species(self):
        by_dex = ap.shadow_ids_by_dex(VANILLA_DARK_POKEMON_LIST)
        self.assertEqual(83, sum(1 for i in range(1, 84) if national_dex_for(VANILLA_DARK_POKEMON_LIST[i])))
        self.assertIn(TEDDIURSA, by_dex)


if __name__ == "__main__":
    unittest.main()
