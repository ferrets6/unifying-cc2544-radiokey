#!/usr/bin/env python3
"""USB device selection shared by all scripts in firmware/tools/.

Reason: with PID split per component (bootloader=0x0010,
bootloader_updater=0x0020, app_tx/app_rx=0x0030), app_tx and app_rx
still share the same PID - with two dongles attached, picking "the
first one found" risks choosing the wrong device (e.g. resetting app_rx
instead of app_tx). Never a silent default when there's more than one
candidate - always ask, showing the physical port + iProduct of each.

With a single candidate, no question asked.
"""
import time
import usb.core


def port_str(dev):
    return f"{dev.bus}-{'.'.join(str(p) for p in dev.port_numbers)}"


def iproduct_or_none(dev):
    try:
        dev.set_configuration()
    except usb.core.USBError:
        pass
    try:
        return dev.product
    except (ValueError, usb.core.USBError):
        return None


def imanufacturer_or_none(dev):
    try:
        dev.set_configuration()
    except usb.core.USBError:
        pass
    try:
        return dev.manufacturer
    except (ValueError, usb.core.USBError):
        return None


def select_device(vid, pid, backend=None, exclude_ports=None, prompt_label=""):
    """Finds all VID:PID devices, excluding ports in exclude_ports (so
    the same physical dongle isn't picked twice - e.g. TX and RX when
    they share a PID, see send_raw_test.py). One candidate: returns it
    directly. More than one: asks the user (port + iProduct). Zero:
    returns None (no waiting here - see select_device_wait for a
    timeout-based retry, e.g. right after a reset)."""
    exclude_ports = exclude_ports or set()
    candidates = [d for d in usb.core.find(idVendor=vid, idProduct=pid, find_all=True, backend=backend)
                  if port_str(d) not in exclude_ports]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    label = f" ({prompt_label})" if prompt_label else ""
    print(f"Found {len(candidates)} dongles with VID:PID {vid:04x}:{pid:04x}{label}:")
    info = [(d, port_str(d), iproduct_or_none(d), imanufacturer_or_none(d)) for d in candidates]
    for i, (d, port, prod, manuf) in enumerate(info):
        print(f" {i + 1}) port {port} - VID:PID {d.idVendor:04x}:{d.idProduct:04x} - "
              f"iManufacturer: {manuf if manuf else '(unreadable)'} - "
              f"iProduct: {prod if prod else '(unreadable)'}")
    while True:
        choice = input("which dongle? > ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(info):
                return info[idx][0]
        except ValueError:
            pass
        print("invalid choice")


def select_device_wait(vid, pid, timeout, backend=None, exclude_ports=None, prompt_label=""):
    """Like select_device, but retries the scan for up to timeout
    seconds if there are zero candidates (e.g. right after a reset,
    before the dongle has reappeared on the bus). As soon as at least
    one candidate shows up, behaves exactly like select_device."""
    t0 = time.time()
    while True:
        dev = select_device(vid, pid, backend=backend, exclude_ports=exclude_ports, prompt_label=prompt_label)
        if dev is not None or time.time() - t0 > timeout:
            return dev
        time.sleep(0.2)


def find_on_port(vid, pid, bus, port_numbers, backend=None):
    """Finds a VID:PID device on an already-known physical port (bus +
    port_numbers) - unambiguous by construction, used to find the SAME
    dongle again after a reset/PID change without asking the user to
    choose again."""
    for d in usb.core.find(idVendor=vid, idProduct=pid, find_all=True, backend=backend):
        if d.bus == bus and tuple(d.port_numbers) == port_numbers:
            return d
    return None
