#!/usr/bin/env python3
"""Rimuove il blocco finale non standard (record type 0xFD, quasi
certamente la firma crittografica) da RQR24.07_B0030.shex, senza
nessun'altra modifica - il file originale non contiene nulla sotto
0x0400 (verificato: indirizzo minimo reale 0x0400), quindi non serve
(e non va aggiunto) nessun salto sintetico né stub di vettori qui.

Il vero bootloader Logitech (BOT03), su un dongle originale intatto,
fornisce lui stesso lo forwarding dei 18 vettori di interrupt reali
verso l'area app rilocata (+0x400) - per questo l'immagine di
aggiornamento applicativo non li include mai, gli update non toccano
mai il bootloader. Il nostro bootloader occupa la stessa area di BOT03
ma non fornisce quel forwarding (design a polling, mai interrupt) - se
il firmware stock ne ha davvero bisogno per funzionare, lo stub va
aggiunto NEL NOSTRO BOOTLOADER (che oggi non ha lo spazio libero per
farlo, vedi firmware/bootloader/README.md), non in questo file. Vedi
README.md per la discussione completa.

Uso: python3 build_with_ivt.py [input.shex] [output.hex]
Default: RQR24.07_B0030.shex -> RQR24.07_B0030_stripped.hex (stessa cartella).
"""
import os
import sys


def parse_ihx(path):
    """Ritorna {addr: byte}. Si ferma al primo record non standard
    (tipo diverso da 0/1/4/5, es. 0xFD la firma) senza tentare di
    interpretarlo - tutto quello letto PRIMA resta valido."""
    data = {}
    ela = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line.startswith(':'):
                continue
            n = int(line[1:3], 16)
            addr = int(line[3:7], 16)
            rectype = int(line[7:9], 16)
            if rectype == 0:
                for i in range(n):
                    data[(ela << 16) + addr + i] = int(line[9 + 2 * i:11 + 2 * i], 16)
            elif rectype == 4:
                ela = int(line[9:13], 16)
            elif rectype == 1:
                break
            elif rectype == 5:
                continue  # start linear address, non ci serve
            else:
                print(f"record tipo 0x{rectype:02x} (probabile firma) - ignorato, "
                      f"fine parsing dati validi", file=sys.stderr)
                break
    return data


def write_ihx(path, data):
    addrs = sorted(data)
    with open(path, 'w') as f:
        i = 0
        while i < len(addrs):
            start = addrs[i]
            chunk = []
            while i < len(addrs) and len(chunk) < 16 and addrs[i] == start + len(chunk):
                chunk.append(data[addrs[i]])
                i += 1
            n = len(chunk)
            rec = f"{n:02X}{start:04X}00" + ''.join(f"{b:02X}" for b in chunk)
            cksum = (-sum(int(rec[j:j + 2], 16) for j in range(0, len(rec), 2))) & 0xFF
            f.write(f":{rec}{cksum:02X}\n")
        f.write(":00000001FF\n")


def main():
    args = sys.argv[1:]
    here = os.path.dirname(os.path.abspath(__file__))
    src = args[0] if len(args) > 0 else os.path.join(here, 'RQR24.07_B0030.shex')
    dst = args[1] if len(args) > 1 else os.path.join(here, 'RQR24.07_B0030_stripped.hex')

    if not os.path.isfile(src):
        print(f"ERRORE: file non trovato: {src}")
        return 1

    data = parse_ihx(src)
    if not data:
        print("ERRORE: nessun byte dati valido letto dal file")
        return 1
    min_addr, max_addr = min(data), max(data)
    print(f"letti {len(data)} byte da {src} (0x{min_addr:04x}-0x{max_addr:04x})")

    if min_addr < 0x0400:
        below = sum(1 for a in data if a < 0x0400)
        print(f"ATTENZIONE: {below} byte sotto 0x0400 nel file originale (inatteso) - "
              f"controllare a mano prima di usare questo output")

    write_ihx(dst, data)
    print(f"scritto {dst} ({len(data)} byte, solo firma rimossa, nessun'altra modifica)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
