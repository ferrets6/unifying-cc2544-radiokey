#!/usr/bin/env python3
"""Sends SOFT_RESET (bRequest=0x04) to a 1209:0030 dongle (app_tx/app_rx)
- makes it enter the bootloader (PID 1209:0010, split from the app) in
its indefinite listening state (iProduct becomes "URBl").

Works on both Linux and Windows. On Windows needs pyusb +
libusb-package (see firmware/WINDOWS_SETUP.md) - the script tries the
default backend first, then libusb_package as a fallback, so it's the
same file on both platforms.

Usage: python soft_reset.py [idProduct_hex]
     (default idProduct = 0x0030, the app - after the reset the PID
     CHANGES to 0x0010, the bootloader)

If there's more than one dongle at the requested PID (e.g. app_tx and
app_rx still share 0x0030), asks which to choose, showing the physical
port + iProduct - never a silent default. After the reset, finds the
SAME dongle on the SAME port, no second choice needed.
"""
import os
import sys
import time
import usb.core

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
import usb_select


def get_backend():
    try:
        usb.core.find(idVendor=0x1209)
        return None  # default backend works (e.g. on Linux)
    except usb.core.NoBackendError:
        pass
    import libusb_package
    return libusb_package.get_libusb1_backend()


def main():
    pid = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x0030
    after_pid = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x0010
    backend = get_backend()

    dev = usb_select.select_device(0x1209, pid, backend=backend)
    if dev is None:
        print(f"dongle 1209:{pid:04x} not found")
        sys.exit(1)
    bus, port_numbers = dev.bus, tuple(dev.port_numbers)

    try:
        dev.set_configuration()
    except usb.core.USBError:
        pass

    print("before:", dev.product)
    dev.ctrl_transfer(0x40, 0x04, 0, 0, None, timeout=1000)
    print("SOFT_RESET sent")

    # Windows takes longer than Linux to complete re-enumeration+driver
    # binding after a disconnect/reconnect - retry instead of a single
    # read after a fixed sleep. Search restricted to the SAME physical
    # port as before - unambiguous by construction, no second choice
    # needed from the user.
    dev2 = None
    t0 = time.time()
    while time.time() - t0 < 10:
        time.sleep(0.5)
        dev2 = usb_select.find_on_port(0x1209, after_pid, bus, port_numbers, backend=backend)
        if dev2 is None:
            continue
        try:
            dev2.set_configuration()
        except usb.core.USBError:
            pass
        try:
            print("after:", dev2.product)
            break
        except ValueError:
            dev2 = None
    else:
        print("after the reset: couldn't read iProduct back within 10s")


if __name__ == "__main__":
    main()
