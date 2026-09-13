#!/usr/bin/env python3
"""
Variant of firmware/bootloader/inject_vectors.py for the minimal
bootloader hand-written in assembly (bootmin.asm) instead of C/SDCC:
same mechanism (forwarding stubs via Intel HEX post-processing), but
APP_BASE=0x0400 (instead of 0x1000, since this bootloader is meant to
fit entirely in 0x0000-0x03FF) and the entry point is looked up in the
.map as `_start` (assembly label), not `__sdcc_gsinit_startup` (SDCC
runtime symbol, absent here since this is pure assembly).

Usage:
    python3 inject_vectors_min.py bootmin_linked.ihx bootmin_final.hex
"""
import sys

APP_BASE = 0x0400

TRUE_VECTORS = [0x0003,0x000B,0x0013,0x001B,0x0023,0x002B,0x0033,0x003B,
                0x0043,0x004B,0x0053,0x005B,0x0063,0x006B,0x0073,0x007B,
                0x0083,0x008B]


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


def write_ihx(data, path):
    addrs = sorted(data.keys())
    with open(path, 'w') as f:
        i = 0
        while i < len(addrs):
            chunk = [addrs[i]]
            j = i + 1
            while j < len(addrs) and addrs[j] == addrs[j - 1] + 1 and len(chunk) < 16:
                chunk.append(addrs[j])
                j += 1
            base = chunk[0]
            byte_vals = [data[a] for a in chunk]
            n = len(byte_vals)
            rec = f'{n:02X}{base:04X}00' + ''.join(f'{b:02X}' for b in byte_vals)
            cksum = (-(sum(bytes.fromhex(rec)))) & 0xFF
            f.write(f':{rec}{cksum:02X}\n')
            i = j
        f.write(':00000001FF\n')


def find_entry(map_path):
    for line in open(map_path):
        if ' _start ' in line or line.rstrip().endswith('_start'):
            parts = line.split()
            return int(parts[1], 16)
    raise RuntimeError(f'_start not found in {map_path}')


def inject_bootloader(ihx_path, map_path, out_path):
    boot = parse_ihx(ihx_path)
    entry = find_entry(map_path)
    boot[0x0000] = 0x02
    boot[0x0001] = (entry >> 8) & 0xFF
    boot[0x0002] = entry & 0xFF
    for v in TRUE_VECTORS:
        target = APP_BASE + v
        boot[v] = 0x02
        boot[v + 1] = (target >> 8) & 0xFF
        boot[v + 2] = target & 0xFF
    write_ihx(boot, out_path)
    print(f'{out_path}: {len(boot)} byte, entry=0x{entry:04x}, max addr 0x{max(boot):04x}')


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    ihx = sys.argv[1]
    out = sys.argv[2]
    map_path = ihx.rsplit('.', 1)[0] + '.map'
    inject_bootloader(ihx, map_path, out)
