#!/usr/bin/env python3
"""Erases and rewrites page 0 (the bootloader) via debug in one command:
calls erase_bootloader_page_via_debug, then (only if the erase
succeeds) write_bootloader_via_debug with the given file. Stops
immediately if the erase fails, never attempting a write on a page not
guaranteed blank.

Usage: sudo python3 flash_bootloader_page_via_debug.py [bootloader.ihx] [-r rst] [-c dc] [-d dd]
Defaults to firmware/bootloader/bin/bootloader.ihx if the file is omitted.
"""
import argparse
import os
import subprocess
import sys

DEBUG_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_IHX = os.path.join(DEBUG_DIR, '..', 'bootloader', 'bin', 'bootloader.ihx')


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
    ap.add_argument('hexfile', nargs='?', default=DEFAULT_IHX)
    ap.add_argument('-r', type=int, default=24)
    ap.add_argument('-c', type=int, default=27)
    ap.add_argument('-d', type=int, default=28)
    args = ap.parse_args()

    pin_args = ['-r', str(args.r), '-c', str(args.c), '-d', str(args.d)]

    erase_tool = build_if_missing('erase_bootloader_page_via_debug')
    write_tool = build_if_missing('write_bootloader_via_debug')

    print("erasing page 0 (bootloader)...")
    r = subprocess.run([erase_tool] + pin_args)
    if r.returncode != 0:
        print("ERROR erasing page 0 - ABORT, write NOT attempted")
        return 1

    print(f"writing {args.hexfile}...")
    r = subprocess.run([write_tool] + pin_args + [args.hexfile])
    if r.returncode != 0:
        print("ERROR writing/verifying - see output above")
        return 1

    print("OK - bootloader erased, rewritten, and verified")
    return 0


if __name__ == '__main__':
    sys.exit(main())
