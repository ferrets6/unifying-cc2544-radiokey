#!/usr/bin/env python3
"""Raw send/receive test between the two dongles over the CC2544 radio
link (firmware/app_tx + firmware/app_rx), no HID semantics.

Usage: python3 send_raw_test.py [attempts]

Requires app_tx already flashed on one dongle and app_rx on the other -
see firmware/tools/flash_firmware.py.
"""
import os
import sys
import time

import usb.core

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
import usb_select

TX_VID, TX_PID = 0x1209, 0x0030
RX_VID, RX_PID = 0x1209, 0x0030
# NOTE: app_tx and app_rx share the same PID 0x0030 (PID split per
# component, not per role) - find() below asks which dongle is TX and
# excludes that port from the RX choice (usb_select.py), so there's no
# risk of picking the same dongle twice by mistake.

SEND_TEST_PACKET = 0x10
GET_LAST_PACKET = 0x11
PKT_LEN = 5


def find(vid, pid, name, exclude_ports=None):
    dev = usb_select.select_device_wait(vid, pid, timeout=10, exclude_ports=exclude_ports, prompt_label=name)
    if dev is None:
        print(f"ERROR: {name} (VID:PID {vid:04x}:{pid:04x}) not found within 10s")
        sys.exit(1)
    try:
        dev.set_configuration()
    except usb.core.USBError:
        pass
    return dev


def main():
    attempts = int(sys.argv[1]) if len(sys.argv) > 1 else 1

    tx = find(TX_VID, TX_PID, "app_tx")
    rx = find(RX_VID, RX_PID, "app_rx", exclude_ports={usb_select.port_str(tx)})
    print(f"app_tx found ({TX_VID:04x}:{TX_PID:04x}), app_rx found ({RX_VID:04x}:{RX_PID:04x})", flush=True)

    # each send carries a DIFFERENT pattern derived from a sequence
    # counter on the TX dongle (pkt[0]=s, pkt[1]=s^0xFF, pkt[2]=s*3&0xFF,
    # pkt[3]=s^0x5A, pkt[4]=s+0x55&0xFF - see app_tx/main.c). The
    # expected value is recomputed here from pkt[0] (which IS s), so a
    # position-dependent bug can be told apart from a value-dependent one.
    ok_count = 0
    byte_error_counts = [0, 0, 0, 0, 0]
    no_pkt_count = 0
    for i in range(attempts):
        print(f"--- attempt {i + 1}/{attempts} ---", flush=True)
        tx.ctrl_transfer(0x40, SEND_TEST_PACKET, 0, 0, None)
        time.sleep(0.05)  # time for the radio round-trip + TX/RX task completion

        resp = bytes(rx.ctrl_transfer(0xC0, GET_LAST_PACKET, 0, 0, 1 + PKT_LEN))
        have = resp[0]
        pkt = resp[1:]
        print(f"  have_pkt={have} pkt={pkt.hex()}", flush=True)

        if not have:
            no_pkt_count += 1
            print("  FAILED: no packet received", flush=True)
            continue

        s = pkt[0]
        expected = bytes([s, s ^ 0xFF, (s * 3) & 0xFF, s ^ 0x5A, (s + 0x55) & 0xFF])
        if pkt == expected:
            print("  OK: pattern received correctly", flush=True)
            ok_count += 1
        else:
            wrong = [j for j in range(PKT_LEN) if pkt[j] != expected[j]]
            for j in wrong:
                byte_error_counts[j] += 1
            print(f"  FAILED: expected={expected.hex()} got={pkt.hex()} wrong_bytes={wrong}", flush=True)

    print(f"\n{ok_count}/{attempts} tests passed", flush=True)
    print(f"no packet: {no_pkt_count}/{attempts}", flush=True)
    print(f"errors per byte position (0-4): {byte_error_counts}", flush=True)
    sys.exit(0 if ok_count == attempts else 1)


if __name__ == '__main__':
    main()
