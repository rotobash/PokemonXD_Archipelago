"""Purification Unlocks -- one item per Shadow slot, written by the client into the AP patch's RAM block.

The item side: 127 frozen names (one per DDPK slot), created only for the slots a seed holds, progression when the
`Purify N` checks count on them and useful otherwise, and each Shadow's purification rung needing its own unlock.
The client side: `ram_client.PurifyUnlockSync` against a fake memory -- it writes only once the patch's hook is
seen, touches only flag bit 2, and puts the whole list back after a cold boot."""
from __future__ import annotations

import struct
import unittest
from unittest import mock

from BaseClasses import ItemClassification

from . import PokemonXDTestBase
from .. import items, locations
from .. import ram_client as rc
from ..game_data import purify_unlocks as pu

PATCHED_HOOK_WORD = 0x48230D49   # bl apMain, from the shipped assets/patch.diff


class TestTheItems(unittest.TestCase):
    def test_one_frozen_item_per_slot(self) -> None:
        self.assertEqual(127, len(items.PURIFY_UNLOCK_ITEM_NAMES))
        for ddpk in pu.ALL_DDPK_INDICES:
            name = pu.unlock_item_name(ddpk)
            self.assertEqual(261 + ddpk, items.ITEM_TABLE[name].id_offset, name)
            self.assertEqual(ddpk, pu.ddpk_for_unlock_item(name))
            self.assertIsNone(items.ITEM_TABLE[name].game_item_id)

    def test_other_names_are_not_unlocks(self) -> None:
        for name in ("Master Ball", "Purify Unlock - Shadow 000", "Purify Unlock - Shadow 128",
                     "Purify Unlock - Shadow abc"):
            self.assertIsNone(pu.ddpk_for_unlock_item(name), name)

    def test_never_drawn_as_filler(self) -> None:
        self.assertFalse(items.PURIFY_UNLOCK_ITEM_NAMES & set(items.FILLER_ITEMS))
        self.assertEqual(items.PURIFY_UNLOCK_ITEM_NAMES, items.ITEM_NAME_GROUPS["Purify Unlocks"])


class TestTheBlock(unittest.TestCase):
    def test_patch_detection(self) -> None:
        self.assertTrue(pu.ap_patch_installed(PATCHED_HOOK_WORD))
        self.assertFalse(pu.ap_patch_installed(pu.VANILLA_AP_MAIN_HOOK_WORD))
        self.assertFalse(pu.ap_patch_installed(0x60000000))   # nop
        self.assertFalse(pu.ap_patch_installed(0x48230D48))   # b, not bl

    def test_encoding_is_counter_then_sorted_list(self) -> None:
        self.assertEqual(bytes.fromhex("0003" "0001" "0054" "007f"), pu.encode_give_purified([127, 84, 1, 84, 0, 128]))
        self.assertEqual(b"\x00\x00", pu.encode_give_purified([]))


class _FakeMemory:
    def __init__(self, hook_word: int) -> None:
        self.bytes: "dict[int, int]" = {}
        self.writes = 0
        self.write(pu.AP_MAIN_HOOK_SITE, struct.pack(">I", hook_word))
        self.writes = 0

    def read(self, address: int, length: int) -> bytes:
        return bytes(self.bytes.get(address + i, 0) for i in range(length))

    def write(self, address: int, data: bytes) -> None:
        self.writes += 1
        for i, b in enumerate(data):
            self.bytes[address + i] = b

    def flags(self) -> int:
        return struct.unpack(">H", self.read(pu.AP_BLOCK_ADDRESS + pu.FLAGS_OFFSET, 2))[0]

    def purified(self) -> "list[int]":
        count = struct.unpack(">H", self.read(pu.AP_BLOCK_ADDRESS + pu.GIVE_PURIFY_COUNTER_OFFSET, 2))[0]
        raw = self.read(pu.AP_BLOCK_ADDRESS + pu.GIVE_PURIFIED_OFFSET, count * 2)
        return [struct.unpack(">H", raw[i:i + 2])[0] for i in range(0, len(raw), 2)]

    def cold_boot(self) -> None:
        hook = self.read(pu.AP_MAIN_HOOK_SITE, 4)
        self.bytes.clear()
        self.bytes.update({pu.AP_MAIN_HOOK_SITE + i: b for i, b in enumerate(hook)})


class TestTheReconciler(unittest.TestCase):
    def _poll(self, memory: _FakeMemory, sync: rc.PurifyUnlockSync, enabled: bool, ddpks) -> "str | None":
        with mock.patch.object(rc, "read_bytes", memory.read), mock.patch.object(rc, "write_bytes", memory.write):
            return sync.poll(enabled, ddpks)

    def test_writes_flag_and_list_then_goes_quiet(self) -> None:
        memory, sync = _FakeMemory(PATCHED_HOOK_WORD), rc.PurifyUnlockSync()
        memory.write(pu.AP_BLOCK_ADDRESS, struct.pack(">H", 0b1011))   # bits 0, 1, 3 belong to other features
        self.assertIsNotNone(self._poll(memory, sync, True, {12, 3}))
        self.assertEqual(0b1111, memory.flags())
        self.assertEqual([3, 12], memory.purified())
        writes = memory.writes
        self.assertIsNone(self._poll(memory, sync, True, {12, 3}))
        self.assertEqual(writes, memory.writes, "an unchanged list must not be rewritten")

    def test_cold_boot_puts_everything_back(self) -> None:
        memory, sync = _FakeMemory(PATCHED_HOOK_WORD), rc.PurifyUnlockSync()
        self._poll(memory, sync, True, {1, 2, 90})
        memory.cold_boot()
        self.assertEqual([], memory.purified())
        self._poll(memory, sync, True, {1, 2, 90})
        self.assertEqual([1, 2, 90], memory.purified())
        self.assertTrue(memory.flags() & (1 << pu.PURIFY_UNLOCK_FLAG_BIT))

    def test_new_unlock_extends_the_list(self) -> None:
        memory, sync = _FakeMemory(PATCHED_HOOK_WORD), rc.PurifyUnlockSync()
        self._poll(memory, sync, True, {5})
        self._poll(memory, sync, True, {5, 40})
        self.assertEqual([5, 40], memory.purified())

    def test_nothing_written_without_the_patch(self) -> None:
        memory, sync = _FakeMemory(pu.VANILLA_AP_MAIN_HOOK_WORD), rc.PurifyUnlockSync()
        self.assertIsNone(self._poll(memory, sync, True, {5}))
        self.assertEqual(0, memory.writes)
        self.assertFalse(sync.installed)

    def test_disabled_clears_only_its_bit(self) -> None:
        memory, sync = _FakeMemory(PATCHED_HOOK_WORD), rc.PurifyUnlockSync()
        memory.write(pu.AP_BLOCK_ADDRESS, struct.pack(">H", 0b1111))
        self._poll(memory, sync, False, {5})
        self.assertEqual(0b1011, memory.flags())
        self.assertEqual([], memory.purified())


def _pool_unlocks(test: PokemonXDTestBase) -> "list":
    return [item for item in test.multiworld.itempool if item.player == test.player
            and item.name in items.PURIFY_UNLOCK_ITEM_NAMES]


class TestUnlocksGateThePurifyChecks(PokemonXDTestBase):
    options = {"purification_unlocks": True, "purification_checks": True, "shadow_pokemon_expansion": 5}

    def test_one_progression_unlock_per_slot(self) -> None:
        world = self.multiworld.worlds[self.player]
        unlocks = _pool_unlocks(self)
        self.assertEqual(sorted(world._purify_unlock_species), sorted(pu.ddpk_for_unlock_item(i.name) for i in unlocks))
        self.assertTrue(all(item.classification & ItemClassification.progression for item in unlocks))
        generated = sum(len(plan["new_pokemon"]) for plan in world._shadow_expansion_plans or ())
        self.assertEqual(83 + generated, len(unlocks))

    def test_expansion_slots_are_pinned_in_order(self) -> None:
        world = self.multiworld.worlds[self.player]
        pinned = [mon["target_ddpk_index"] for plan in world._shadow_expansion_plans or () for mon in plan["new_pokemon"]]
        self.assertEqual(list(range(pu.FIRST_EXPANSION_DDPK_INDEX, pu.FIRST_EXPANSION_DDPK_INDEX + len(pinned))), pinned)

    def test_slot_data_names_every_slot(self) -> None:
        world = self.multiworld.worlds[self.player]
        slot_data = world.fill_slot_data()
        self.assertTrue(slot_data["purification_unlocks"])
        self.assertEqual({str(k) for k in world._purify_unlock_species}, set(slot_data["purify_unlock_species"]))

    def test_purify_one_needs_an_unlock(self) -> None:
        name = locations.purification_location_name(1)
        self.collect_all_but(sorted(items.PURIFY_UNLOCK_ITEM_NAMES))
        self.assertFalse(self.can_reach_location(name))
        self.collect_by_name(pu.unlock_item_name(1))   # the HQ Lab's Teddiursa, the first Shadow there is
        self.assertTrue(self.can_reach_location(name))


class TestUnlocksWithoutPurifyChecks(PokemonXDTestBase):
    options = {"purification_unlocks": True, "purification_checks": False}

    def test_unlocks_are_useful(self) -> None:
        unlocks = _pool_unlocks(self)
        self.assertEqual(len(self.multiworld.worlds[self.player]._purify_unlock_species), len(unlocks))
        self.assertTrue(unlocks)
        self.assertTrue(all(item.classification == ItemClassification.useful for item in unlocks))


class TestUnlocksOff(PokemonXDTestBase):
    options = {"purification_unlocks": False}

    def test_no_unlocks(self) -> None:
        self.assertEqual([], _pool_unlocks(self))
        self.assertNotIn("purify_unlock_species", self.multiworld.worlds[self.player].fill_slot_data())
