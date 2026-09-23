#!/usr/bin/env python3
"""Writes any firmware/app (Intel HEX) using the bootloader's USB
protocol: FLASH_STARTED, then ERASE_PAGE+WRITE_CHUNK per page/chunk,
then FLASH_FINISHED.

Usage: flash_firmware.py [firmware.ihx] [port] [pid_hex]
<firmware.ihx> is optional: if omitted, picks from the compiled images
in firmware/*/bin/ (asks which one if there's more than one).

<port> (e.g. "1-1.4"/"1-1.5", see firmware/DONGLE_MAP.md) is optional:
if omitted and there's a single dongle candidate, proceeds directly;
otherwise asks which one (port+iProduct, see
firmware/tools/lib/usb_select.py).

[pid_hex] optional, default "0010" (the real bootloader): use "0020" to
talk to an already-active bootloader_updater instead. PID scheme, split
per component: bootloader=0x0010, bootloader_updater=0x0020,
app_tx/app_rx=0x0030.

No need to reset the dongle by hand first: if the target is the real
bootloader (default PID 0010) and the dongle found is instead running
the app (PID 0030), the script sends a SOFT_RESET itself and waits for
it to come back as the bootloader on the same physical port. Already in
the bootloader? Proceeds directly (listening is indefinite, no timing
window to respect).

Used both to load a real firmware/app and to load bootloader_updater.ihx
into the app area when the bootloader itself needs rewriting (see
update_bootloader.py) - same protocol either way, only the file changes.
"""
import os, sys, time
import usb.core

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
import usb_select

VID = 0x1209
APP_BASE = 0x0400  # page 0 (below this address) is the bootloader itself
ERASE_PAGE = 0x01
WRITE_CHUNK = 0x02
FLASH_STARTED = 0x04
FLASH_FINISHED = 0x05
MAX_CHUNK = 252
PAGE_SIZE = 1024


def parse_port(port_str):
    """'1-1.4' -> (bus=1, port_numbers=(1, 4)). Same format as
    lsusb -t / DONGLE_MAP.md."""
    bus_str, path_str = port_str.split('-', 1)
    return int(bus_str), tuple(int(p) for p in path_str.split('.'))


FIRMWARE_ROOT = os.path.join(os.path.dirname(__file__), '..')
BIN_DIRS = ['app_tx/bin', 'app_rx/bin', 'bootloader/bin']


def find_firmware_images():
    """Lists the compiled images available in firmware/*/bin/."""
    images = []
    for rel in BIN_DIRS:
        d = os.path.join(FIRMWARE_ROOT, rel)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.endswith('.ihx'):
                images.append(os.path.join(d, fn))
    return images


def looks_like_port(s):
    return bool(s) and '-' in s and '.' in s and s.replace('-', '').replace('.', '').isdigit()


def select_firmware_path(explicit):
    """If explicit is an existing path, uses it directly. Otherwise
    searches firmware/*/bin/: one image proceeds directly, more than
    one asks which (never a silent default)."""
    if explicit and os.path.isfile(explicit):
        return explicit
    images = find_firmware_images()
    if not images:
        print("No compiled image found in firmware/*/bin/ - build first (see the various README.md)")
        sys.exit(1)
    if len(images) == 1:
        return images[0]
    print("Available compiled images:")
    rel = [os.path.relpath(p, FIRMWARE_ROOT) for p in images]
    for i, r in enumerate(rel):
        print(f" {i + 1}) {r}")
    while True:
        choice = input("which image? > ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(images):
                return images[idx]
        except ValueError:
            pass
        print("invalid choice")


def find_device_on_port(vid, pid, bus, port_numbers, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        for dev in usb.core.find(idVendor=vid, idProduct=pid, find_all=True):
            if dev.bus == bus and tuple(dev.port_numbers) == port_numbers:
                return dev, time.time() - t0
    return None, time.time() - t0


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


def flash(dev, hex_path):
    """Writes hex_path (Intel HEX, addresses >= APP_BASE only) to the
    already-found/selected device. Extracted from main() so other
    scripts can reuse it with a device already chosen elsewhere,
    without duplicating the erase/write/FLASH_FINISHED logic."""
    data = parse_ihx(hex_path)

    # SAFETY: explicitly rejects any byte < APP_BASE (0x0400) - that's
    # the bootloader's page. This function never touches it: rewriting
    # the bootloader needs bootloader_updater.ihx + update_bootloader.py.
    below = {a: b for a, b in data.items() if a < APP_BASE}
    if below:
        print(f"SAFETY ERROR: {len(below)} bytes below APP_BASE (0x{APP_BASE:04x}) in the file - IGNORED, will not be written")
    data = {a: b for a, b in data.items() if a >= APP_BASE}
    if not data:
        print("ERROR: no bytes >= APP_BASE found in the file")
        return False

    # The bootloader writes whole 4-byte flash words (nwords = wLength>>2)
    # and silently drops a trailing partial word - align both ends,
    # padding with 0xFF (erased flash).
    min_addr = min(data) & ~3
    max_addr = max(data) | 3
    full =bytes(data.get(a, 0xFF) for a in range(min_addr, max_addr + 1))
    pages = list(range(min_addr // PAGE_SIZE, max_addr // PAGE_SIZE + 1))

    try:
        dev.set_configuration()
    except usb.core.USBError:
        pass

    print(f"loading 0x{min_addr:04x}-0x{max_addr:04x} ({len(full)} bytes), pages {pages}...", flush=True)

    print(f'FLASH_STARTED ({len(full)} bytes)...', flush=True)
    dev.ctrl_transfer(0x40, FLASH_STARTED, len(full), 0, None)

    for page in pages:
        print(f'  erase page {page}...', flush=True)
        dev.ctrl_transfer(0x40, ERASE_PAGE, page, 0, None)
        print('  OK', flush=True)

    addr = min_addr
    off = 0
    while off < len(full):
        chunk = full[off:off + MAX_CHUNK]
        print(f'  write 0x{addr:04x} ({len(chunk)} bytes)...', flush=True)
        dev.ctrl_transfer(0x40, WRITE_CHUNK, addr, 0, chunk)
        print('  OK', flush=True)
        addr += len(chunk)
        off += len(chunk)

    print('FLASH_FINISHED...', flush=True)
    try:
        status = bytes(dev.ctrl_transfer(0xC0, FLASH_FINISHED, 0, 0, 1))
        print(f"status: 0x{status[0]:02x} ({'OK' if status[0]==0 else 'MISMATCH'})", flush=True)
    except usb.core.USBError as e:
        print(f"(error on status response: {e} - known cosmetic quirk of the Raspberry's USB controller, the jump happens anyway)", flush=True)

    print("Done - the chip should now boot the firmware just written.", flush=True)
    return True


SOFT_RESET = 0x04
APP_PID = 0x0030


def reset_app_and_wait(vid, app_dev, target_pid, bus, port_numbers, timeout):
    """The app found instead of the bootloader gets reset (SOFT_RESET,
    same command as COMMANDS.md) and we wait for it to reappear with
    target_pid on the SAME physical port - never a fresh, ambiguous
    search."""
    port = f"{bus}-{'.'.join(str(p) for p in port_numbers)}"
    print(f"app running on port {port} - sending SOFT_RESET...", flush=True)
    try:
        app_dev.ctrl_transfer(0x40, SOFT_RESET, 0, 0, None, timeout=1000)
    except usb.core.USBError:
        pass  # expected: the dongle disconnects before the host sees the ack
    dev, dt = find_device_on_port(vid, target_pid, bus, port_numbers, timeout)
    if dev is not None:
        print(f"bootloader found on port {port} after reset ({dt:.3f}s)", flush=True)
    return dev


def find_bootloader(vid, pid, port_arg, timeout=10):
    """Finds the device at PID pid (default 0010, the real bootloader).
    If not found but the same physical unit is found running the app
    (PID 0030) instead, resets it and waits for it to reappear - only
    when pid is the default bootloader PID (for an explicit different
    PID, e.g. bootloader_updater 0020, the app doesn't implement that
    protocol and auto-reset wouldn't make sense)."""
    quick = 3  # immediate check - the common case (dongle already in
               # one of the two states) doesn't need a long wait
    if port_arg is not None:
        bus, port_numbers = parse_port(port_arg)
        dev, dt = find_device_on_port(vid, pid, bus, port_numbers, quick)
        if dev is not None:
            print(f"bootloader found on port {port_arg} after {dt:.3f}s", flush=True)
            return dev
        if pid == 0x0010:
            app_dev, _ = find_device_on_port(vid, APP_PID, bus, port_numbers, quick)
            if app_dev is not None:
                return reset_app_and_wait(vid, app_dev, pid, bus, port_numbers, timeout)
        print(f"no dongle (bootloader or app) found on port {port_arg}")
        return None
    else:
        dev = usb_select.select_device_wait(vid, pid, timeout=quick)
        if dev is not None:
            print(f"bootloader found on port {usb_select.port_str(dev)}", flush=True)
            return dev
        if pid == 0x0010:
            app_dev = usb_select.select_device_wait(vid, APP_PID, timeout=quick)
            if app_dev is not None:
                bus, port_numbers = parse_port(usb_select.port_str(app_dev))
                return reset_app_and_wait(vid, app_dev, pid, bus, port_numbers, timeout)
        print("no dongle (bootloader or app) found")
        return None


def main():
    args = sys.argv[1:]
    explicit_path = None
    if args and not looks_like_port(args[0]):
        explicit_path = args.pop(0)
    port_arg = args.pop(0) if args and looks_like_port(args[0]) else None
    PID = int(args.pop(0), 16) if args else 0x0010

    path = select_firmware_path(explicit_path)

    dev = find_bootloader(VID, PID, port_arg)
    if dev is None:
        sys.exit(1)

    if not flash(dev, path):
        sys.exit(1)
    print("Check with: dmesg | tail -20", flush=True)


if __name__ == '__main__':
    main()
