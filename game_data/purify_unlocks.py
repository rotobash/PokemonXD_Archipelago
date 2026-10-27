"""Purification Unlocks -- one AP item per Shadow slot; a Shadow cannot be purified until its unlock arrives.

THE SLOT. A Shadow's identity in the game is its DDPK index (`DeckData_DarkPokemon.bin`), the id the relive-flag
functions take: `zz_shadow_id_get_start_of_stored_shadow_data` indexes the save's stored Shadow records with it
directly (`id < 0x80`, 0x48 bytes each). Vanilla uses 1-83 (0 is the sentinel); Shadow Pokemon Expansion fills
84 upwards in plan order (`__init__` pins each one's `target_ddpk_index`, so generation and the ISO patcher agree).
Nightmare Citadark / the removal options MOVE a Shadow to another trainer but keep its DDPK index. So an item named
for a slot means the same Shadow in every seed; only its species is per-seed, which is why the species is not in
the item name (a datapackage name is fixed across seeds) but in slot data, for the client to say.

THE BLOCK. The AP patch (`assets/patch.diff`, source `patch.c`) keeps a struct at 0x81700000. The client owns
`give.purified[]`: the DDPK indices it has received unlocks for, `give.purifyCounter` long. The patch's
`apPatchAbleToPurify` answers "not purifiable" for any Shadow not in the list while flag bit 2 is set. The block is
RAM, so a cold boot zeroes it; the client rewrites the whole list whenever it does not match what was received.
Offsets confirmed against the compiled patch (`lhz r9, 0xF94(r9)` in apPatchAbleToPurify, `addi r9, r10, 0x7C8;
slwi r9, r9, 1` for the array):

    +0x000  u16 flags                bit 2 = AP_ENABLE_PURIFYCHECKS
    +0xF94  u16 give.purifyCounter
    +0xF96  u16 give.purified[128]

PATCH DETECTION. The block is ordinary game memory on an ISO without the patch, so nothing is written there until
the patch's `cmpHero` hook is seen in RAM: the vanilla `bl cmpHero` at 0x801BE06C becomes a `bl apMain`. Any `bl`
there that is not the vanilla one counts, so a rebuilt patch with its code at another address still passes.

Import-free so the standalone patcher can load it by path.
"""
from __future__ import annotations

AP_BLOCK_ADDRESS = 0x81700000
FLAGS_OFFSET = 0x000
PURIFY_UNLOCK_FLAG_BIT = 2                     # AP_ENABLE_PURIFYCHECKS
GIVE_PURIFY_COUNTER_OFFSET = 0xF94
GIVE_PURIFIED_OFFSET = 0xF96
GIVE_PURIFIED_CAPACITY = 0x80                  # NUMBER_OF_SHADOW_POKEMON

AP_MAIN_HOOK_SITE = 0x801BE06C                 # AppScript's `bl cmpHero`
VANILLA_AP_MAIN_HOOK_WORD = 0x480038C5         # bl 0x801C1930 (cmpHero)

FIRST_DDPK_INDEX = 1
FIRST_EXPANSION_DDPK_INDEX = 84                # vanilla's 83 are 1-83, contiguous
LAST_DDPK_INDEX = 127                          # 128 records, 0 the sentinel

ITEM_NAME_PREFIX = "Purify Unlock - Shadow "


def unlock_item_name(ddpk_index: int) -> str:
    return f"{ITEM_NAME_PREFIX}{int(ddpk_index):03d}"


def ddpk_for_unlock_item(item_name: str) -> "int | None":
    """The DDPK index an unlock item names, or None for any other item."""
    if not item_name.startswith(ITEM_NAME_PREFIX):
        return None
    tail = item_name[len(ITEM_NAME_PREFIX):]
    if not tail.isdigit():
        return None
    index = int(tail)
    return index if FIRST_DDPK_INDEX <= index <= LAST_DDPK_INDEX else None


ALL_DDPK_INDICES: "tuple[int, ...]" = tuple(range(FIRST_DDPK_INDEX, LAST_DDPK_INDEX + 1))


def ap_patch_installed(hook_word: int) -> bool:
    """True when the word at AP_MAIN_HOOK_SITE is a `bl` other than the vanilla one."""
    is_bl = (hook_word >> 26) == 18 and (hook_word & 0b11) == 0b01
    return is_bl and hook_word != VANILLA_AP_MAIN_HOOK_WORD


def encode_give_purified(ddpk_indices) -> bytes:
    """`give.purifyCounter` then `give.purified[]`, big-endian, for one contiguous write. Sorted and de-duplicated
    so the same received set always encodes to the same bytes, which is what the reconcile compares."""
    wanted = sorted({int(i) for i in ddpk_indices if FIRST_DDPK_INDEX <= int(i) <= LAST_DDPK_INDEX})
    out = bytearray(len(wanted).to_bytes(2, "big"))
    for index in wanted:
        out += index.to_bytes(2, "big")
    return bytes(out)
