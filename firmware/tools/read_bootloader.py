#!/usr/bin/env python3
"""Reads back (READ-ONLY, zero risk) the bootloader page (0x0000-0x03FF,
1024 bytes by default) via READ_CHUNK from bootloader_updater (must
already be loaded in the app area - see README.md).

Usage:
  read_bootloader.py                        reads 1024 bytes from 0x0000,
                                             saves to bootloader_readback.bin
  read_bootloader.py <address> <n> [port]   reads n bytes from any address
                                             (also useful to verify a
                                             firmware/app just written to
                                             other pages)

<port> (e.g. "1-1.4", see firmware/DONGLE_MAP.md) is optional - if
omitted and bootloader_updater is active on more than one dongle at
once, asks which to choose instead of picking one at random.
"""
import os, sys, time
import usb.core

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
import usb_select

VID, PID = 0x1209, 0x0020
READ_CHUNK = 0x03
CHUNK = 200
FIND_TIMEOUT = 30.0


def parse_port(port_str):
    bus_str, path_str = port_str.split('-', 1)
    return int(bus_str), tuple(int(p) for p in path_str.split('.'))


def read_page0(dev, addr=0, length=1024):
    """Extracted from main() so other scripts can reuse it (e.g. a
    post-reset final check) without duplicating the READ_CHUNK loop.
    Returns the bytes read, doesn't save to a file."""
    try:
        dev.set_configuration()
    except usb.core.USBError:
        pass
    time.sleep(0.2)

    data = b''
    off = 0
    while off < length:
        n = min(CHUNK, length - off)
        chunk = bytes(dev.ctrl_transfer(0xC0, READ_CHUNK, addr + off, 0, n, timeout=3000))
        data += chunk
        off += n
    return data


def main():
    port_arg = None
    if len(sys.argv) > 1:
        addr = int(sys.argv[1], 0)
        length = int(sys.argv[2])
        out_path = None
        if len(sys.argv) > 3:
            port_arg = sys.argv[3]
    else:
        addr = 0
        length = 1024
        out_path = 'bootloader_readback.bin'

    t0 = time.time()
    dev = None
    if port_arg is None:
        dev = usb_select.select_device_wait(VID, PID, timeout=FIND_TIMEOUT)
    else:
        bus, port_numbers = parse_port(port_arg)
        while dev is None and time.time() - t0 < FIND_TIMEOUT:
            for cand in usb.core.find(idVendor=VID, idProduct=PID, find_all=True):
                if cand.bus == bus and tuple(cand.port_numbers) == port_numbers:
                    dev = cand
                    break
    if dev is None:
        print(f"bootloader_updater (PID 0020{', port ' + port_arg if port_arg else ''}) not found - make sure it's loaded via flash_firmware.py")
        sys.exit(1)
    print(f"found after {time.time()-t0:.3f}s, reading 0x{addr:04x}-0x{addr+length-1:04x} ({length} bytes)...", flush=True)

    data = read_page0(dev, addr, length)

    if out_path:
        with open(out_path, 'wb') as f:
            f.write(data)
        print(f"Saved to {out_path} ({len(data)} bytes)")
    print(f"First 32 bytes: {data[:32].hex()}")


if __name__ == '__main__':
    main()
