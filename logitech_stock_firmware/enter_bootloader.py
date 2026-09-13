#!/usr/bin/env python3
"""Forza un ricevitore Logitech Unifying (firmware STOCK) a riavviarsi nel
suo bootloader USB originale (046d:c52b -> 046d:aaac/c52b bootloader PID),
da riga di comando, senza passare da fwupd/un vero aggiornamento firmware.

Comando HID++ 1.0 standard (non specifico di fwupd/del tool ufficiale) -
fonte primaria: fwupd, plugins/logitech-hidpp/fu-logitech-hidpp-runtime-
unifying.c, funzione fu_logitech_hidpp_runtime_unifying_detach():

    report_id = SHORT (0x10)
    device_id = RECEIVER (0xFF)
    sub_id    = SET_REGISTER (0x80)
    register  = DEVICE_FIRMWARE_UPDATE_MODE (0xF0)
    data      = "ICP" (0x49 0x43 0x50)

Pacchetto HID++ short completo (7 byte): 10 FF 80 F0 49 43 50

Uso:
    sudo python3 enter_bootloader.py /dev/hidraw0

Trova il device giusto con:
    for d in /sys/class/hidraw/hidraw*; do
        echo "$(basename $d) -> $(readlink -f $d/device)"
    done
(serve l'hidraw dell'interfaccia del RICEVITORE stesso, non quello di un
dispositivo accoppiato figlio - di solito l'interfaccia ":1.2" del
ricevitore, il primo hidraw elencato per quel percorso).
"""
import sys

PACKET = bytes([0x10, 0xFF, 0x80, 0xF0, 0x49, 0x43, 0x50])


def main():
    if len(sys.argv) != 2:
        print(f"uso: {sys.argv[0]} /dev/hidrawN", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    try:
        with open(path, "wb") as f:
            f.write(PACKET)
    except BrokenPipeError:
        # Atteso: il dispositivo si disconnette a meta' write() perche' il
        # comando innesca subito il reset - non e' un fallimento.
        pass
    print(f"comando ENTER_BOOTLOADER (ICP) inviato a {path}")
    print("controlla: dmesg | tail -10  (dovrebbe apparire un idProduct diverso, bootloader)")


if __name__ == "__main__":
    main()
