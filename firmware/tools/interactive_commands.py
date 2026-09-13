#!/usr/bin/env python3
"""Interactive console to send any USB vendor command by hand - both
bootloader v2 commands and app_tx/app_rx ones - for manual testing
(e.g. trying every key one by one). Works on Windows (pyusb +
libusb-package, see firmware/WINDOWS_SETUP.md) and Linux/Pi (default
backend) unchanged.

Usage: python interactive_commands.py [idProduct_hex]
     If omitted, asks which component (PID split per component):
     bootloader=0x0010, bootloader_updater=0x0020, app_tx/app_rx=0x0030.
     All menu commands are shown together regardless (bootloader 1-4,
     common app 5-6, app_tx 7-10, app_rx 11-12) - the user knows which
     ones make sense given what's connected; the PID choice is only to
     find the right device.

If more than one dongle is connected with the chosen PID (e.g. app_tx
and app_rx still share 0x0030), asks which to pick showing physical
port + iProduct - never a silent default (see
firmware/tools/lib/usb_select.py). The "refresh" (r) command finds the
SAME dongle on the SAME physical port, trying all known PIDs (useful
after SOFT_RESET/APP_RESTART/RESET_STAGE1, which change the PID) - no
second choice needed.

SAFETY: ERASE_PAGE and WRITE_CHUNK (bootloader) reject by construction
any address/page below 0x0400 (page 0 = the bootloader itself) - same
protection as tools/flash_firmware.py, applied here too to manually
sent commands.
"""
import os
import sys
import time
import usb.core

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
import usb_select

VID = 0x1209
APP_BASE = 0x0400
KNOWN_PIDS = (0x0010, 0x0020, 0x0030)

# Minimal letter->HID usage code table, for convenience - any other key
# can be entered directly as a hex code (see USB HID Usage Tables,
# Keyboard/Keypad Page 0x07).
HID_KEYS = {
    "a": 0x04, "b": 0x05, "c": 0x06, "d": 0x07, "e": 0x08, "f": 0x09,
    "g": 0x0A, "h": 0x0B, "i": 0x0C, "j": 0x0D, "k": 0x0E, "l": 0x0F,
    "m": 0x10, "n": 0x11, "o": 0x12, "p": 0x13, "q": 0x14, "r": 0x15,
    "s": 0x16, "t": 0x17, "u": 0x18, "v": 0x19, "w": 0x1A, "x": 0x1B,
    "y": 0x1C, "z": 0x1D,
    "1": 0x1E, "2": 0x1F, "3": 0x20, "4": 0x21, "5": 0x22,
    "6": 0x23, "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27,
    "enter": 0x28, "esc": 0x29, "backspace": 0x2A, "tab": 0x2B,
    "space": 0x2C, "-": 0x2D, "=": 0x2E,
    "up": 0x52, "down": 0x51, "left": 0x50, "right": 0x4F,
}
MODIFIERS = {"none": 0x00, "shift": 0x02, "ctrl": 0x01, "alt": 0x04, "gui": 0x08}


def get_backend():
    try:
        usb.core.find(idVendor=VID)
        return None
    except usb.core.NoBackendError:
        pass
    import libusb_package
    return libusb_package.get_libusb1_backend()


def find_device(backend, pid):
    return usb_select.select_device(VID, pid, backend=backend)


def refresh_same_port(backend, bus, port_numbers):
    """Finds the same physical dongle (bus+port_numbers) trying all
    known PIDs - after a command that changes PID (SOFT_RESET,
    APP_RESTART, RESET_STAGE1) the old PID stops responding, but the
    physical port stays the same: nothing to ask the user again."""
    for pid in KNOWN_PIDS:
        dev = usb_select.find_on_port(VID, pid, bus, port_numbers, backend=backend)
        if dev is not None:
            return dev, pid
    return None, None


def refresh(dev):
    try:
        dev.set_configuration()
    except usb.core.USBError:
        pass
    try:
        prod = dev.product
    except ValueError:
        prod = "(unreadable string)"
    return prod


def ask_int(prompt, base=10, default=None):
    s = input(prompt).strip()
    if s == "" and default is not None:
        return default
    return int(s, base)


def ask_hex_bytes(prompt):
    s = input(prompt).strip()
    if not s:
        return b""
    parts = s.replace(",", " ").split()
    return bytes(int(p, 16) for p in parts)


MENU = """
=== {prod} (PID {pid:04x}) ===

--- bootloader (v2) ---
 1) ERASE_PAGE        - erase an app page (>=1, never page 0)
 2) WRITE_CHUNK        - write bytes at an address (>=0x0400)
 3) FLASH_STARTED      - declare total length of a write session
 4) FLASH_FINISHED     - read status (0=OK, 1=mismatch), jumps to app if OK

--- common app (usb_core.c) ---
 5) SOFT_RESET         - trigger the watchdog, enters bootloader within ~1s
 6) APP_RESTART        - restart the app WITHOUT going through the bootloader
13) GET_LAST_RESET_CAUSE - cause of the last REAL reset (00=power-on/brownout, 01=RESET_N, 10=watchdog, 11=clock-loss)

--- app_tx ---
 7) SEND_TEST_PACKET   - sends a diagnostic radio packet (variable pattern)
 8) SEND_KEY down      - presses a key (radio) - stays down until you send up
 9) SEND_KEY up        - releases a key (radio)
10) GET_RADIO_DEBUG    - radio state + last send outcome (TX only)

--- app_rx ---
11) GET_LAST_PACKET    - last radio packet received (raw)
12) GET_RADIO_DEBUG    - radio state (RX)

--- misc ---
 r) refresh (re-read iProduct - useful after a reset)
 q) quit
"""


PID_CHOICES = {
    "1": ("bootloader", 0x0010),
    "2": ("bootloader_updater", 0x0020),
    "3": ("app_tx/app_rx", 0x0030),
}


def ask_pid():
    print("Which component? (PID split per component)")
    for k, (name, pid) in PID_CHOICES.items():
        print(f" {k}) {name} (0x{pid:04x})")
    while True:
        choice = input("choice> ").strip()
        if choice in PID_CHOICES:
            return PID_CHOICES[choice][1]
        print("invalid choice")


def main():
    pid = int(sys.argv[1], 16) if len(sys.argv) > 1 else ask_pid()
    backend = get_backend()

    dev = find_device(backend, pid)
    if dev is None:
        print(f"dongle 1209:{pid:04x} not found")
        sys.exit(1)
    bus, port_numbers = dev.bus, tuple(dev.port_numbers)
    prod = refresh(dev)

    while True:
        print(MENU.format(prod=prod, pid=pid))
        choice = input("choice> ").strip().lower()

        try:
            if choice == "q":
                break

            elif choice == "r":
                dev, new_pid = refresh_same_port(backend, bus, port_numbers)
                if dev is None:
                    print("dongle not found on the same port (maybe still re-enumerating)")
                    continue
                pid = new_pid
                prod = refresh(dev)

            elif choice == "1":
                page = ask_int("page number (>=1): ")
                if page < 1:
                    print("REJECTED: page 0 is the bootloader, never touch it from here")
                    continue
                dev.ctrl_transfer(0x40, 0x01, page, 0, None)
                print("ERASE_PAGE sent")

            elif choice == "2":
                addr = ask_int("hex address (e.g. 400): ", 16)
                if addr < APP_BASE:
                    print(f"REJECTED: address below 0x{APP_BASE:04x} (bootloader page)")
                    continue
                data = ask_hex_bytes("hex bytes separated by spaces (e.g. 'aa bb cc'): ")
                dev.ctrl_transfer(0x40, 0x02, addr, 0, data)
                print(f"WRITE_CHUNK sent ({len(data)} bytes)")

            elif choice == "3":
                length = ask_int("declared total length: ")
                dev.ctrl_transfer(0x40, 0x04, length, 0, None)
                print("FLASH_STARTED sent")

            elif choice == "4":
                status = dev.ctrl_transfer(0xC0, 0x05, 0, 0, 1, timeout=2000)
                s = status[0]
                print(f"FLASH_FINISHED status = 0x{s:02x} ({'OK, should jump to app' if s == 0 else 'MISMATCH, stays listening'})")

            elif choice == "5":
                dev.ctrl_transfer(0x40, 0x04, 0, 0, None, timeout=1000)
                print("SOFT_RESET sent (only works if the device is running the app - in the bootloader 0x04 is FLASH_STARTED, see menu 3)")

            elif choice == "6":
                try:
                    dev.ctrl_transfer(0x40, 0x05, 0, 0, None, timeout=1000)
                except usb.core.USBError as e:
                    print(f"(expected error, cosmetic quirk: {e})")
                print("APP_RESTART sent")

            elif choice == "7":
                dev.ctrl_transfer(0x40, 0x10, 0, 0, None)
                print("SEND_TEST_PACKET sent")

            elif choice in ("8", "9"):
                key = input("key (letter/digit, or name tab/enter/esc/space/up/down/..., or hex 0x..): ").strip().lower()
                if key.startswith("0x"):
                    kc = int(key, 16)
                elif key in HID_KEYS:
                    kc = HID_KEYS[key]
                else:
                    print("unrecognized key")
                    continue
                mod_name = input(f"modifier [{'/'.join(MODIFIERS)}] (enter = none): ").strip().lower() or "none"
                mod = MODIFIERS.get(mod_name, 0x00)
                downup = 1 if choice == "8" else 0
                wValue = (mod << 8) | kc
                dev.ctrl_transfer(0x40, 0x13, wValue, 0, bytes([downup]))
                print(f"SEND_KEY {'down' if downup else 'up'} sent (mod=0x{mod:02x} key=0x{kc:02x})")

            elif choice == "10":
                dbg = bytes(dev.ctrl_transfer(0xC0, 0x12, 0, 0, 6, timeout=2000))
                print(f"GET_RADIO_DEBUG: LLESTAT={dbg[0]:02x} PRF_ENDCAUSE={dbg[1]:02x} rx_armed={dbg[2]:02x} RSSI={dbg[3]:02x} last_send_ok={dbg[4]:02x} last_send_rounds={dbg[5]:02x}")

            elif choice == "11":
                resp = bytes(dev.ctrl_transfer(0xC0, 0x11, 0, 0, 32, timeout=2000))
                print(f"GET_LAST_PACKET: have_pkt={resp[0]:02x} data={resp[1:].hex()}")

            elif choice == "12":
                dbg = bytes(dev.ctrl_transfer(0xC0, 0x12, 0, 0, 5, timeout=2000))
                print(f"GET_RADIO_DEBUG: LLESTAT={dbg[0]:02x} PRF_ENDCAUSE={dbg[1]:02x} rx_armed={dbg[2]:02x} RSSI={dbg[3]:02x} last_len={dbg[4]:02x}")

            elif choice == "13":
                cause = dev.ctrl_transfer(0xC0, 0x06, 0, 0, 1, timeout=2000)[0]
                names = {0: "power-on/brownout", 1: "external RESET_N", 2: "watchdog", 3: "clock-loss"}
                print(f"GET_LAST_RESET_CAUSE: {cause:02b} ({names.get(cause, '?')})")

            else:
                print("invalid choice")

        except usb.core.USBError as e:
            print(f"USB ERROR: {e}")
        except ValueError as e:
            print(f"input error: {e}")


if __name__ == "__main__":
    main()
