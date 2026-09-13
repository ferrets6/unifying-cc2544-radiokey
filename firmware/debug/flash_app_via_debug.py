#!/usr/bin/env python3
"""Writes any firmware (ours or third-party, e.g. stock Logitech) to the
app area via debug, without ever touching page 0 (the bootloader):
computes which 1024-byte pages the file needs, erases them one by one
with erase_page_via_debug (which refuses page 0), then writes with
write_app_via_debug (which refuses to write below 0x0400). Aborts with
an error if the file contains bytes below 0x0400 - same protection as
flash_firmware.py.

Usage: sudo python3 flash_app_via_debug.py <file.hex|.ihx> [-r rst] [-c dc] [-d dd]
"""
import argparse
import os
import subprocess
import sys

DEBUG_DIR = os.path.dirname(os.path.abspath(__file__))
PAGE_LEN = 1024
APP_BASE = 0x0400


KNOWN_RECORD_TYPES = {0, 1, 4, 5}  # data, EOF, extended linear addr, start linear addr


def parse_ihx(path):
    """Raises ValueError on any non-standard record type (e.g. a
    trailing signature block, type 0xFD) - must stop here, before
    erasing any page, rather than letting the C write tool discover it
    after the erase already happened."""
    data = {}
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            if not line.startswith(':'):
                raise ValueError(f"line {lineno}: doesn't start with ':'")
            n = int(line[1:3], 16)
            addr = int(line[3:7], 16)
            rectype = int(line[7:9], 16)
            if rectype not in KNOWN_RECORD_TYPES:
                raise ValueError(f"line {lineno}: unrecognized record type 0x{rectype:02x} "
                                  f"(not a standard .ihx/.hex - probably a signature or metadata "
                                  f"block not stripped, see logitech_stock_firmware/README.md)")
            if rectype != 0:
                continue
            for i in range(n):
                data[addr + i] = int(line[9 + 2 * i:11 + 2 * i], 16)
    return data


def build_if_missing(name):
    path = os.path.join(DEBUG_DIR, name)
    if not os.path.exists(path):
        print(f"building {name}...")
        subprocess.run(['gcc', '-Wall', '-o', path,
                         os.path.join(DEBUG_DIR, f'{name}.c'),
                         os.path.join(DEBUG_DIR, 'CCDebugger.c'), '-lwiringPi'], check=True)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('hexfile')
    ap.add_argument('-r', type=int, default=24)
    ap.add_argument('-c', type=int, default=27)
    ap.add_argument('-d', type=int, default=28)
    args = ap.parse_args()

    if not os.path.isfile(args.hexfile):
        print(f"ERROR: file not found: {args.hexfile}")
        return 1

    try:
        data = parse_ihx(args.hexfile)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1
    below = {a: b for a, b in data.items() if a < APP_BASE}
    if below:
        print(f"SAFETY ERROR: {len(below)} bytes below 0x{APP_BASE:04x} (page 0, bootloader) in the file - ABORT")
        return 1
    if not data:
        print("ERROR: no bytes in the file")
        return 1

    min_addr, max_addr = min(data), max(data)
    pages = sorted(set(a // PAGE_LEN for a in data))
    print(f"File: 0x{min_addr:04x}-0x{max_addr:04x} ({len(data)} bytes), pages {pages}")

    pin_args = ['-r', str(args.r), '-c', str(args.c), '-d', str(args.d)]

    erase_tool = build_if_missing('erase_page_via_debug')
    for page in pages:
        print(f"erasing page {page}...")
        r = subprocess.run([erase_tool, '-p', str(page)] + pin_args)
        if r.returncode != 0:
            print(f"ERROR erasing page {page} - ABORT (later pages left untouched)")
            return 1

    write_tool = build_if_missing('write_app_via_debug')
    r = subprocess.run([write_tool] + pin_args + [args.hexfile])
    if r.returncode != 0:
        print("ERROR writing/verifying - see output above")
        return 1

    print("OK - app area written and verified, page 0 (bootloader) never touched")
    return 0


if __name__ == '__main__':
    sys.exit(main())
