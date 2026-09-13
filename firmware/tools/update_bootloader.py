#!/usr/bin/env python3
"""Rewrites the bootloader (page 0, 0x0000-0x03FF) over USB, end to end:

1. If the dongle is running our own firmware (app_tx/app_rx), offers to
   back up the current app first (GET_APP_DUMP) - loading
   bootloader_updater overwrites the whole app area, so this is the
   last chance to save it.
2. Loads bootloader_updater.ihx into the app area.
3. Writes and verifies the new bootloader byte-for-byte
   (FLASH_STARTED -> ERASE_STAGE1 -> WRITE_STAGE1_CHUNK -> READ_CHUNK).
   Never calls FLASH_FINISHED and never resets on its own - a mismatch
   leaves bootloader_updater alive so you can just retry.
4. On success, asks whether to reboot into the bootloader only, or
   reboot and restore the app that was backed up in step 1.

Usage: update_bootloader.py [bootloader.ihx] [port]
<bootloader.ihx> is optional: defaults to the compiled image in
firmware/bootloader/bin/ (asks which one if there's more than one).
<port> (e.g. "1-1.4") is optional: needed only when multiple dongles
are attached at once.
"""
import os
import sys
import time

import usb.core

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
import usb_select
import flash_firmware
import dump_app

VID = 0x1209
APP_PID = 0x0030
BOOTLOADER_PID = 0x0010
UPDATER_PID = 0x0020

ERASE_STAGE1 = 0x10
WRITE_STAGE1_CHUNK = 0x11
READ_CHUNK = 0x03
FLASH_STARTED = 0x04
RESET_STAGE1 = 0x12
MAX_CHUNK = 252
FIND_TIMEOUT = 30.0
PAGE_LEN = 1024

BOOTLOADER_BIN = os.path.join(os.path.dirname(__file__), '..', 'bootloader', 'bin')


def select_bootloader_hex(explicit):
    if explicit and os.path.isfile(explicit):
        return explicit
    if not os.path.isdir(BOOTLOADER_BIN):
        print(f"No {BOOTLOADER_BIN} - build it first (see firmware/bootloader/README.md)")
        sys.exit(1)
    # exclude bootloader_updater.ihx: valid file, wrong target (goes to
    # the app area via flash_firmware.py, not page 0)
    images = sorted(os.path.join(BOOTLOADER_BIN, fn) for fn in os.listdir(BOOTLOADER_BIN)
                     if fn.endswith('.ihx') and 'updater' not in fn)
    if not images:
        print(f"No compiled image in {BOOTLOADER_BIN} - build it first")
        sys.exit(1)
    if len(images) == 1:
        return images[0]
    print("Available images:")
    for i, p in enumerate(images):
        print(f" {i + 1}) {os.path.basename(p)}")
    while True:
        choice = input("which one? > ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(images):
                return images[idx]
        except ValueError:
            pass
        print("invalid choice")


def parse_ihx(path):
    data = {}
    ela = 0
    for line in open(path):
        line = line.strip()
        if not line.startswith(':'):
            continue
        n = int(line[1:3], 16)
        addr = int(line[3:7], 16)
        rtype = int(line[7:9], 16)
        if rtype == 4:
            ela = int(line[9:13], 16)
            continue
        if rtype != 0:
            continue
        payload = line[9:9 + n * 2]
        for i in range(n):
            data[(ela << 16) + addr + i] = int(payload[i * 2:i * 2 + 2], 16)
    return data


def find_device(port=None):
    t0 = time.time()
    if port is None:
        dev = usb_select.select_device_wait(VID, UPDATER_PID, timeout=FIND_TIMEOUT)
        return dev, time.time() - t0
    bus, port_numbers = port
    while time.time() - t0 < FIND_TIMEOUT:
        for dev in usb.core.find(idVendor=VID, idProduct=UPDATER_PID, find_all=True):
            if dev.bus == bus and tuple(dev.port_numbers) == port_numbers:
                return dev, time.time() - t0
    return None, time.time() - t0


def write_and_verify(dev, hex_path):
    """Never calls FLASH_FINISHED, never resets - returns True/False,
    caller decides what to do next."""
    data = parse_ihx(hex_path)
    expected = bytes(data.get(a, 0xFF) for a in range(PAGE_LEN))
    content_len = max(data) + 1
    print(f"Image to write: {content_len} real bytes (rest of the page is 0xFF)", flush=True)

    try:
        dev.set_configuration()
    except usb.core.USBError:
        pass
    time.sleep(0.3)

    try:
        print(f"FLASH_STARTED ({content_len} bytes)...", flush=True)
        dev.ctrl_transfer(0x40, FLASH_STARTED, content_len, 0, None)

        print("ERASE_STAGE1 (page 0, the bootloader)...", flush=True)
        dev.ctrl_transfer(0x40, ERASE_STAGE1, 0, 0, None)
        print("  OK", flush=True)

        addr = 0
        off = 0
        while off < content_len:
            chunk = expected[off:off + MAX_CHUNK]
            print(f"WRITE_STAGE1_CHUNK 0x{addr:04x} ({len(chunk)} bytes)...", flush=True)
            dev.ctrl_transfer(0x40, WRITE_STAGE1_CHUNK, addr, 0, chunk)
            print("  OK", flush=True)
            addr += len(chunk)
            off += len(chunk)

        print("\nWrite complete. No FLASH_FINISHED sent (session stays open, no timeout).", flush=True)
        print("Reading back the full page (1024 bytes) via READ_CHUNK for a byte-for-byte check...\n", flush=True)

        readback = b''
        addr = 0
        while addr < PAGE_LEN:
            n = min(200, PAGE_LEN - addr)
            chunk = bytes(dev.ctrl_transfer(0xC0, READ_CHUNK, addr, 0, n, timeout=3000))
            readback += chunk
            addr += n

        with open('bootloader_readback.bin', 'wb') as f:
            f.write(readback)

        if readback == expected:
            print("=" * 60)
            print("VERIFIED: all 1024 readback bytes match the expected image.")
            print("No reset done - reset is the point of no return.")
            print("=" * 60)
            return True
        else:
            n_diff = sum(1 for a, b in zip(expected, readback) if a != b)
            first = next(i for i in range(PAGE_LEN) if expected[i] != readback[i])
            print("=" * 60)
            print(f"MISMATCH: {n_diff}/1024 bytes differ. First at 0x{first:04x}: expected={expected[first]:02x} got={readback[first]:02x}")
            print("No reset done - bootloader_updater is still alive, you can just retry.")
            print("Do NOT physically unplug/reset the dongle unless the debug clip is attached:")
            print("page 0 is mid-write right now, a real power-on would run it as-is.")
            print("=" * 60)
            return False
    except Exception as e:
        print(f"\nEXCEPTION: {e}")
        print("No reset done in any case by this function.")
        return False


def reset_stage1(dev):
    """RESET_STAGE1 on the SAME device object (never a fresh search,
    which could ambiguously match another one) - triggers a real
    hardware reset via watchdog, no debug clip needed."""
    dev.ctrl_transfer(0x40, RESET_STAGE1, 0, 0, None, timeout=1000)


def preflight_and_maybe_dump(port_arg):
    """Returns (dump_path or None, physical port string or None)."""
    dev = None
    port_str = port_arg
    if port_arg is not None:
        bus, port_numbers = flash_firmware.parse_port(port_arg)
        dev, _ = flash_firmware.find_device_on_port(VID, APP_PID, bus, port_numbers, 2)
    else:
        dev = usb_select.select_device_wait(VID, APP_PID, timeout=2)
        if dev is not None:
            port_str = usb_select.port_str(dev)

    if dev is None:
        print("No dongle found in 'app' state (PID 0030) - if it's already in the "
              "bootloader, there's no current app to save here.")
        input("If you proceed without an existing backup, you'll be stuck in the new "
              "bootloader with no way to recover the app. Press ENTER to continue anyway, "
              "Ctrl+C to stop... ")
        return None, port_str

    if not dump_app.can_dump(dev):
        print("The running firmware isn't ours (no response to GET_APP_DUMP) - can't back it up.")
        input("If you proceed, that firmware is overwritten and lost for good - you'll be "
              "stuck in the new bootloader. Press ENTER to continue anyway, Ctrl+C to stop... ")
        return None, port_str

    answer = input("The dongle is running our firmware. Back up the current app before "
                    "proceeding? [Y/n] > ").strip().lower()
    if answer == 'n':
        print("No backup made - if something goes wrong, that app is lost for good.")
        return None, port_str

    dump_path = os.path.join(os.path.dirname(__file__), '..', '..', 'app_dump.ihx')
    if not dump_app.dump(dev, dump_path):
        print("Backup failed - see error above.")
        sys.exit(1)
    return dump_path, port_str


def main():
    args = sys.argv[1:]
    explicit_path = None
    if args and not flash_firmware.looks_like_port(args[0]):
        explicit_path = args.pop(0)
    port_arg = args.pop(0) if args else None

    bootloader_path = select_bootloader_hex(explicit_path)

    dump_path, port_str = preflight_and_maybe_dump(port_arg)

    print("\nloading bootloader_updater into the app area...", flush=True)
    updater_path = os.path.join(BOOTLOADER_BIN, 'bootloader_updater.ihx')
    dev = flash_firmware.find_bootloader(VID, BOOTLOADER_PID, port_str)
    if dev is None:
        sys.exit(1)
    if not flash_firmware.flash(dev, updater_path):
        sys.exit(1)

    print("\nwaiting for bootloader_updater...", flush=True)
    port = flash_firmware.parse_port(port_str) if port_str else None
    dev, dt = find_device(port)
    if dev is None:
        print(f"bootloader_updater not found within {FIND_TIMEOUT}s")
        sys.exit(1)
    print(f"found after {dt:.3f}s", flush=True)

    if not write_and_verify(dev, bootloader_path):
        sys.exit(1)

    if dump_path is not None:
        prompt = ("\nBootloader written and verified.\n"
                   "1) Reboot into the bootloader (no app started)\n"
                   f"2) Reboot and restore the backed-up app ({dump_path})\n"
                   "Choice [1/2] > ")
    else:
        prompt = ("\nBootloader written and verified. Reboot into the bootloader? "
                   "To start the app afterward, run jump_to_app.py from there. [y/N] > ")

    answer = input(prompt).strip().lower()
    if dump_path is not None and answer == '2':
        reset_stage1(dev)
        print("RESET_STAGE1 sent, waiting for the new bootloader...", flush=True)
        time.sleep(1.0)
        new_dev = flash_firmware.find_bootloader(VID, BOOTLOADER_PID, port_str)
        if new_dev is None:
            print("New bootloader not found - retry by hand with flash_firmware.py.")
            sys.exit(1)
        if not flash_firmware.flash(new_dev, dump_path):
            sys.exit(1)
        print("App restored.")
    elif answer in ('y', '1'):
        reset_stage1(dev)
        print("RESET_STAGE1 sent. Check with: lsusb -d 1209:")
    else:
        print("No reset sent - the new bootloader is written but not active until you "
              "reboot it (rerun this script, or by hand: "
              "ctrl_transfer(0x40, 0x12, 0, 0, None) on the same device).")


if __name__ == '__main__':
    main()
