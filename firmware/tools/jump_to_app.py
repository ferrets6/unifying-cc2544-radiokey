#!/usr/bin/env python3
"""Makes the bootloader (PID 0x0010, listening) jump straight into the
app WITHOUT writing anything: declares a zero-length flash session
(FLASH_STARTED) and closes it right away (FLASH_FINISHED) -
WRITTEN_LEN(0) == EXPECTED_LEN(0) is always a match, so the bootloader
jumps to the app exactly as after a real successful flash (same clean
USB disconnect/reconnect before the jump, see bootloader.asm
ff_jump_app). Never touches flash.

Useful after RESET_STAGE1 (update_bootloader.py): that's a real
hardware reset, so the new bootloader always comes back listening,
never directly in the app (see bootloader.asm - only a real power-on or
FLASH_FINISHED jump to the app). This script is the USB-only way to
finish that transition, no physical unplug/replug needed.

Usage: python3 jump_to_app.py [port]
The port (e.g. "1-1.5") is optional - if omitted and there's a single
bootloader candidate, proceeds directly; otherwise asks which one.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
import usb_select

VID = 0x1209
PID = 0x0010
FLASH_STARTED = 0x04
FLASH_FINISHED = 0x05


def parse_port(port_str):
    bus_str, path_str = port_str.split('-', 1)
    return int(bus_str), tuple(int(p) for p in path_str.split('.'))


def main():
    port_arg = sys.argv[1] if len(sys.argv) > 1 else None

    if port_arg is not None:
        bus, port_numbers = parse_port(port_arg)
        dev = usb_select.find_on_port(VID, PID, bus, port_numbers)
        if dev is None:
            print(f"bootloader (PID 0010) not found on port {port_arg}")
            sys.exit(1)
    else:
        dev = usb_select.select_device_wait(VID, PID, timeout=3)
        if dev is None:
            print("bootloader (PID 0010) not found")
            sys.exit(1)

    print(f"bootloader found on port {usb_select.port_str(dev)}", flush=True)
    dev.ctrl_transfer(0x40, FLASH_STARTED, 0, 0, None)
    try:
        status = bytes(dev.ctrl_transfer(0xC0, FLASH_FINISHED, 0, 0, 1))
        print(f"status: 0x{status[0]:02x} ({'OK, jumping to app' if status[0] == 0 else 'unexpected MISMATCH'})")
    except Exception as e:
        print(f"(no status response: {e} - known cosmetic quirk, the jump happens anyway)")

    print("Check with: lsusb -d 1209:")


if __name__ == '__main__':
    main()
