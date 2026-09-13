#!/usr/bin/env python3
"""Compares page 0 (the bootloader, 1024 bytes) read from the chip via
debug against firmware/bootloader/bin/bootloader.ihx byte-for-byte - to
verify the bootloader on the chip is exactly our unmodified build.
Read-only, no write.

Usage: sudo python3 check_bootloader_via_debug.py [-r rst] [-c dc] [-d dd]
"""
import argparse
import os
import subprocess
import sys

REPO_ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
DEBUG_DIR = os.path.join(REPO_ROOT, 'firmware', 'debug')
BOOTLOADER_IHX = os.path.join(REPO_ROOT, 'firmware', 'bootloader', 'bin', 'bootloader.ihx')
PAGE_LEN = 1024


def parse_ihx(path):
    data = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line.startswith(':'):
                continue
            n = int(line[1:3], 16)
            addr = int(line[3:7], 16)
            rectype = int(line[7:9], 16)
            if rectype != 0:
                continue
            for i in range(n):
                data[addr + i] = int(line[9 + 2 * i:11 + 2 * i], 16)
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-r', type=int, default=24)
    ap.add_argument('-c', type=int, default=27)
    ap.add_argument('-d', type=int, default=28)
    args = ap.parse_args()

    if not os.path.isfile(BOOTLOADER_IHX):
        print(f"ERROR: reference file not found: {BOOTLOADER_IHX}")
        return 1

    dump_prefix = '/tmp/bootloader_check'
    dump_tool = os.path.join(DEBUG_DIR, 'dump_all_via_debug')
    if not os.path.exists(dump_tool):
        subprocess.run(['gcc', '-Wall', '-o', dump_tool,
                         os.path.join(DEBUG_DIR, 'dump_all_via_debug.c'),
                         os.path.join(DEBUG_DIR, 'CCDebugger.c'), '-lwiringPi'], check=True)

    r = subprocess.run([dump_tool, '-r', str(args.r), '-c', str(args.c), '-d', str(args.d), dump_prefix])
    if r.returncode != 0:
        print("ERROR reading via debug - see output above")
        return 1

    with open(f'{dump_prefix}_flash_8000_FFFF.bin', 'rb') as f:
        actual = f.read(PAGE_LEN)

    data = parse_ihx(BOOTLOADER_IHX)
    expected = bytes(data.get(a, 0xFF) for a in range(PAGE_LEN))

    if actual == expected:
        print(f"IDENTICAL to {BOOTLOADER_IHX} - bootloader unmodified ({PAGE_LEN} bytes compared)")
        return 0
    else:
        diffs = [i for i in range(PAGE_LEN) if actual[i] != expected[i]]
        print(f"DIFFERENT: {len(diffs)} bytes differ out of {PAGE_LEN}")
        print(f"  first at offset 0x{diffs[0]:04x}: expected 0x{expected[diffs[0]]:02x}, got 0x{actual[diffs[0]]:02x}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
