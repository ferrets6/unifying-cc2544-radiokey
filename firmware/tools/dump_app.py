#!/usr/bin/env python3
"""Backs up the current app area (0x0400 onward) by reading it from the
dongle via GET_APP_DUMP (bRequest 0x07, available only if our own
firmware - app_tx/app_rx - is running, not a third-party firmware that
doesn't implement this command). Use before a bootloader update (see
update_bootloader.py): that path goes through bootloader_updater, which
overwrites the whole app area - afterward there's no way to recover
what was there unless a backup was made now, while the app is still
alive.

Reads up to the end of flash (0x7FFF, 32KB total on this chip) and
saves an .ihx with only the real content (trims trailing unwritten
0xFF). Can take a few seconds (~1000 32-byte USB transactions).

Usage: python3 dump_app.py [output.ihx] [port]
Default output: app_dump.ihx at the repo root.
"""
import os
import sys
import time

import usb.core

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
import usb_select

VID = 0x1209
PID = 0x0030
GET_APP_DUMP = 0x07
APP_BASE = 0x0400
FLASH_END = 0x8000  # 32KB total on this chip, exclusive
CHUNK = 32


def parse_port(port_str):
    bus_str, path_str = port_str.split('-', 1)
    return int(bus_str), tuple(int(p) for p in path_str.split('.'))


def write_ihx(path, data):
    """data: dict {addr: byte}. Same format used elsewhere in this repo
    (16-byte contiguous records, standard checksum)."""
    addrs = sorted(data)
    with open(path, 'w') as f:
        i = 0
        while i < len(addrs):
            start = addrs[i]
            chunk = []
            while i < len(addrs) and len(chunk) < 16 and addrs[i] == start + len(chunk):
                chunk.append(data[addrs[i]])
                i += 1
            n = len(chunk)
            rec = f"{n:02X}{start:04X}00" + ''.join(f"{b:02X}" for b in chunk)
            cksum = (-sum(int(rec[j:j + 2], 16) for j in range(0, len(rec), 2))) & 0xFF
            f.write(f":{rec}{cksum:02X}\n")
        f.write(":00000001FF\n")


def can_dump(dev):
    """True if the device responds to GET_APP_DUMP (so it's running our
    firmware) - False for third-party firmware that doesn't implement
    the command (or if it's not in app state at all)."""
    try:
        dev.ctrl_transfer(0xC0, GET_APP_DUMP, APP_BASE, 0, 1, timeout=1000)
        return True
    except usb.core.USBError:
        return False


def dump(dev, out_path):
    """Reads the whole app area from the already-found/selected device
    and saves it to out_path (Intel HEX, real content only, trailing
    0xFF trimmed). Returns True/False."""
    print(f"reading 0x{APP_BASE:04x}-0x{FLASH_END - 1:04x} ({FLASH_END - APP_BASE} bytes)...", flush=True)
    raw = bytearray()
    addr = APP_BASE
    t0 = time.time()
    while addr < FLASH_END:
        n = min(CHUNK, FLASH_END - addr)
        chunk = bytes(dev.ctrl_transfer(0xC0, GET_APP_DUMP, addr, 0, n, timeout=1000))
        raw += chunk
        addr += n
        if (addr - APP_BASE) % 3200 == 0:
            print(f"  {addr - APP_BASE}/{FLASH_END - APP_BASE} bytes...", flush=True)
    print(f"read in {time.time() - t0:.1f}s", flush=True)

    last_real = -1
    for i in range(len(raw) - 1, -1, -1):
        if raw[i] != 0xFF:
            last_real = i
            break
    if last_real < 0:
        print("ERROR: app area is completely empty (all 0xFF) - nothing real to save")
        return False

    data = {APP_BASE + i: raw[i] for i in range(last_real + 1)}
    write_ihx(out_path, data)
    print(f"wrote {out_path} ({len(data)} real bytes, 0x{APP_BASE:04x}-0x{APP_BASE + last_real:04x})")
    return True


def main():
    args = sys.argv[1:]
    out_path = args[0] if len(args) > 0 else os.path.join(
        os.path.dirname(__file__), '..', '..', 'app_dump.ihx')
    port_arg = args[1] if len(args) > 1 else None

    if port_arg is not None:
        bus, port_numbers = parse_port(port_arg)
        dev = usb_select.find_on_port(VID, PID, bus, port_numbers)
    else:
        dev = usb_select.select_device_wait(VID, PID, timeout=3)

    if dev is None:
        print("dongle in app state (PID 0030) not found")
        sys.exit(1)
    print(f"dongle found on port {usb_select.port_str(dev)}", flush=True)

    if not can_dump(dev):
        print("ERROR: GET_APP_DUMP doesn't respond - the running firmware isn't ours "
              "(app_tx/app_rx), it doesn't implement this command. No dump possible from here.")
        sys.exit(1)

    if not dump(dev, out_path):
        sys.exit(1)


if __name__ == '__main__':
    main()
