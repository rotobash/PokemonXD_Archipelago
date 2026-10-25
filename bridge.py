r"""
Pokemon XD RAM research bridge.

Runs on YOUR Windows machine, next to a running Dolphin with Pokemon XD loaded. It watches a "commands"
folder for small JSON files (written remotely) and executes them against Dolphin's live memory via
dolphin_memory_engine -- the same, stock/unmodified-Dolphin-compatible library Archipelago's own
Wind Waker client uses. No Dolphin fork or scripting build is required.

USAGE
-----
1. pip install dolphin-memory-engine
2. Start Dolphin, load Pokemon XD, get into a save file / the overworld.
3. Run this script:  python bridge.py
4. Leave it running. It will print status lines. Commands placed in bridge/commands/ get processed
   automatically; results appear in bridge/responses/ and bridge/dumps/.
5. Ctrl+C to stop.

There is nothing to configure -- it uses the folder it's run from as the working directory root.

CHANGE (2026-09-06): the ISO/CISO disc-image commands (iso_info/iso_read/iso_dump/iso_copy/iso_write) that
used to live here have been split out into iso_bridge.py, a separate script with zero dependency on
dolphin_memory_engine or a running emulator -- run that alongside this one (or by itself, if you don't need
live-memory access right now) for ISO-patch work. Both scripts watch the same bridge/commands folder; each
only claims the command types it recognizes and leaves everything else alone, so it's safe to run either or
both. This script now only ever handles the live-Dolphin-memory commands (ping/read/write/write_batch/dump).
"""

import json
import struct
import time
import traceback
from pathlib import Path

import dolphin_memory_engine as dme

ROOT = Path(__file__).resolve().parent
COMMANDS_DIR = ROOT / "bridge" / "commands"
DONE_DIR = ROOT / "bridge" / "commands" / "done"
RESPONSES_DIR = ROOT / "bridge" / "responses"
DUMPS_DIR = ROOT / "bridge" / "dumps"

for d in (COMMANDS_DIR, DONE_DIR, RESPONSES_DIR, DUMPS_DIR):
    d.mkdir(parents=True, exist_ok=True)

STRUCT_FORMATS = {
    "u8": ">B", "s8": ">b",
    "u16": ">H", "s16": ">h",
    "u32": ">I", "s32": ">i",
    "u64": ">Q", "s64": ">q",
    "f32": ">f", "f64": ">d",
}


def parse_addr(value) -> int:
    if isinstance(value, int):
        return value
    return int(value, 16) if str(value).lower().startswith("0x") else int(value)


def do_ping(cmd: dict) -> dict:
    return {"hooked": dme.is_hooked()}


def do_read(cmd: dict) -> dict:
    address = parse_addr(cmd["address"])
    as_type = cmd.get("as", "bytes")
    if as_type == "bytes":
        length = int(cmd["length"])
        data = dme.read_bytes(address, length)
        return {"address": hex(address), "length": length, "hex": data.hex()}
    fmt = STRUCT_FORMATS[as_type]
    size = struct.calcsize(fmt)
    data = dme.read_bytes(address, size)
    (value,) = struct.unpack(fmt, data)
    return {"address": hex(address), "as": as_type, "value": value}


def do_write(cmd: dict) -> dict:
    address = parse_addr(cmd["address"])
    as_type = cmd.get("as", "bytes")
    if as_type == "bytes":
        data = bytes.fromhex(cmd["hex"])
    else:
        fmt = STRUCT_FORMATS[as_type]
        data = struct.pack(fmt, cmd["value"])
    dme.write_bytes(address, data)
    return {"address": hex(address), "as": as_type, "written_bytes": len(data)}


def do_write_batch(cmd: dict) -> dict:
    """Apply several writes in one command round-trip. Each entry in `writes` uses the same shape as a
    top-level `write` command (address/as/value or address/as="bytes"/hex). Applied in list order; if one
    entry fails, its error is recorded and the rest still run (a batch is a convenience for round-trip count,
    not a transaction)."""
    results = []
    for i, entry in enumerate(cmd["writes"]):
        try:
            results.append({"index": i, "ok": True, "result": do_write(entry)})
        except Exception as exc:  # noqa: BLE001 -- one bad entry shouldn't stop the rest of the batch
            results.append({"index": i, "ok": False, "error": str(exc)})
    return {"count": len(results), "results": results}


def do_dump(cmd: dict) -> dict:
    address = parse_addr(cmd["address"])
    length = int(cmd["length"])
    dump_id = cmd["id"]
    out_path = DUMPS_DIR / f"{dump_id}.bin"
    # Read in chunks; dolphin_memory_engine can be unreliable with very large single reads.
    chunk_size = 0x10000
    with open(out_path, "wb") as f:
        remaining = length
        offset = 0
        while remaining > 0:
            n = min(chunk_size, remaining)
            f.write(dme.read_bytes(address + offset, n))
            offset += n
            remaining -= n
    return {"address": hex(address), "length": length, "file": str(out_path.relative_to(ROOT))}


HANDLERS = {
    "ping": do_ping, "read": do_read, "write": do_write, "write_batch": do_write_batch, "dump": do_dump,
}


def process_one(cmd_file: Path) -> None:
    cmd = json.loads(cmd_file.read_text())
    cmd_id = cmd.get("id", cmd_file.stem)
    cmd_type = cmd.get("type")
    response = {"id": cmd_id, "type": cmd_type, "received_at": time.time()}
    print(f"[{cmd_id}] {cmd_type} received -- processing...")
    t0 = time.time()
    try:
        if not dme.is_hooked():
            dme.hook()
        handler = HANDLERS[cmd_type]
        response["ok"] = True
        response["result"] = handler(cmd)
        print(f"[{cmd_id}] {cmd_type} -> ok ({time.time() - t0:.2f}s)")
    except Exception as exc:  # noqa: BLE001 -- report every failure back, never crash the loop
        response["ok"] = False
        response["error"] = str(exc)
        response["traceback"] = traceback.format_exc()
        print(f"[{cmd_id}] {cmd_type} -> ERROR: {exc}")
    (RESPONSES_DIR / f"{cmd_id}.json").write_text(json.dumps(response, indent=2))

    # Move the processed command out of the watched folder so it isn't picked up again. If something with
    # the same filename already exists in DONE_DIR (e.g. a reused/duplicate id from an earlier run), fall
    # back to a timestamped name instead of crashing -- previously, a name collision here raised out of
    # process_one() uncaught, which meant the *same* command file (never moved out of COMMANDS_DIR) got
    # re-globbed and re-processed on every single poll forever, permanently blocking every other command
    # queued after it in filename-sort order from ever being reached.
    dest = DONE_DIR / cmd_file.name
    if dest.exists():
        dest = DONE_DIR / f"{cmd_file.stem}_{time.time_ns()}{cmd_file.suffix}"
    cmd_file.rename(dest)


# Mirrors DolphinComm::DolphinAccessor::DolphinStatus from the underlying C++ engine.
STATUS_NAMES = {0: "hooked", 1: "notRunning", 2: "noEmu", 3: "unHooked"}


def status_name() -> str:
    try:
        return ""
    except Exception as exc:  # noqa: BLE001
        return f"error({exc})"


def try_hook() -> bool:
    """Hook, forcing a clean un_hook() first in case the engine's internal state is stuck.

    A plain repeated dme.hook() call was observed to never succeed inside this long-running loop even
    though a single fresh one-off `hook()` call (in a brand new process) succeeded immediately. The most
    likely explanation is that the engine caches connection state internally and doesn't re-scan properly
    after a failed attempt unless explicitly un-hooked first. This forces that reset every retry.
    """
    if dme.is_hooked():
        return True
    try:
        dme.un_hook()
    except Exception:  # noqa: BLE001 -- un_hook() failing is fine, we're about to hook() anyway
        pass
    try:
        dme.hook()
    except Exception:  # noqa: BLE001 -- report via status_name() below rather than raising
        pass
    return dme.is_hooked()


def main() -> None:
    print(f"Bridge running. Watching: {COMMANDS_DIR}")
    print(f"Handles: {', '.join(sorted(HANDLERS))}. ISO/CISO disc-image commands (iso_info/iso_read/iso_dump/"
          "iso_copy/iso_write) now live in the separate iso_bridge.py -- run that alongside this one (or by")
    print("itself) for ISO-patch work; it doesn't need Dolphin at all. Both scripts share this same commands")
    print("folder and each only claims the command types they recognize.")
    print("Attempting to hook Dolphin...")
    if try_hook():
        print("Hooked Dolphin successfully. Status:", status_name())
    else:
        print("Could not hook Dolphin yet. Status:", status_name(), "-- will keep retrying.")

    last_hook_state = dme.is_hooked()
    last_status_print = 0.0
    while True:
        try:
            hooked_now = dme.is_hooked()
            if hooked_now != last_hook_state:
                last_hook_state = hooked_now
                print(
                    "Dolphin hook status changed:",
                    "connected" if hooked_now else "LOST",
                    "-- status:", status_name(),
                )
            if not hooked_now:
                try_hook()
                now = time.time()
                if now - last_status_print > 3:
                    last_status_print = now
                    print("Still not hooked. Current status:", status_name())

            for cmd_file in sorted(COMMANDS_DIR.glob("*.json")):
                try:
                    cmd_type = json.loads(cmd_file.read_text()).get("type")
                except Exception:  # noqa: BLE001 -- an unreadable/malformed file: leave it for a human to look at
                    continue
                if cmd_type not in HANDLERS:
                    continue  # not ours -- leave it for iso_bridge.py (or whatever else is watching this folder)
                try:
                    process_one(cmd_file)
                except Exception:  # noqa: BLE001 -- never let one bad command file wedge the whole batch
                    traceback.print_exc()
        except KeyboardInterrupt:
            raise
        except Exception:  # noqa: BLE001 -- keep the loop alive no matter what
            traceback.print_exc()
        time.sleep(0.5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped.")
