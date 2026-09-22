# unifying-cc2544-radiokey

Custom firmware for two Logitech Unifying dongles (TI CC2544) turning
them into a point-to-point radio link for HID keystrokes: a hand-written
USB bootloader, a radio driver (CC2544 Link Layer Engine, Auto Mode with
hardware ACK/retransmit), and a minimal USB HID keyboard on the
receiving end.

This is the transport layer, not a keyboard: the RX side already enumerates
as a real HID keyboard, but the TX side has no physical key input yet -
today a key press is only triggered via a USB vendor command sent from a
script (see `firmware/tools/interactive_commands.py`).
[remote-kvm](https://github.com/ferrets6/remote-kvm) is that frontend: it
drives this transport as one of several pluggable HID drivers behind a web
page that also shows live video from the target machine.

Not compatible with the real Logitech Unifying protocol - single fixed
radio pipe, no encryption, no pairing. It reuses the same chip and the
same reliability mechanism the real firmware uses, nothing else.

## Layout

- `firmware/bootloader/` - the USB bootloader (page 0, hand-written
  8051 assembly) and `bootloader_updater` (the bridge used to rewrite
  the bootloader itself over USB).
- `firmware/app_tx/`, `firmware/app_rx/` - the two application images
  (C, SDCC).
- `firmware/app_common/` - USB core and radio driver shared by both apps.
- `firmware/debug/` - tools that talk to the chip over the 2-wire debug
  interface (RST/DC/DD), for when USB alone isn't enough (bootstrapping
  a blank chip, or recovering from a bad flash).
- `firmware/tools/` - host-side USB scripts (flashing, diagnostics).
- `firmware/DONGLE_MAP.md`, `firmware/WINDOWS_SETUP.md` - hardware/OS
  notes.
- `logitech_stock_firmware/` - disassembly and analysis of the real
  Logitech firmware for this chip, used as a reference (register values,
  timing) while building the radio driver.
- `references/` - the TI CC2544 datasheet (SWRU283B) and excerpts used
  throughout the code comments.
- `COMMANDS.md` - the full list of USB vendor commands each stage
  responds to.

## Building

Bootloader (`firmware/bootloader/README.md` has the full recipe):
```
cd firmware/bootloader/src
sdas8051 -los bootloader.rel bootloader.asm
sdcc -mmcs51 --code-loc 0x0090 --out-fmt-ihx -o bootloader_linked.ihx bootloader.rel
python3 inject_vectors_min.py bootloader_linked.ihx ../bin/bootloader.ihx
```

Application (`app_tx`/`app_rx`, same pattern for both):
```
cd firmware/app_tx/src
sdcc -mmcs51 -c -o usb_core.rel ../../app_common/usb_core.c
sdcc -mmcs51 -c -o radio.rel ../../app_common/radio.c
sdcc -mmcs51 -c -o main.rel main.c
sdcc -mmcs51 --code-loc 0x0400 --out-fmt-ihx -o ../bin/app_tx.ihx main.rel usb_core.rel radio.rel
```
(`app_rx` also compiles and links `usb_hid.c`.)

Compiled `.ihx` images are committed under each `bin/` folder, ready to
flash.

## Flashing

See `COMMANDS.md` and `firmware/tools/update_bootloader.py --help`-style
docstrings for the USB-only flow (bootloader, app, bootloader update with
automatic app backup). `firmware/debug/README.md` covers the debug-clip
path, needed only for the very first bootloader flash on a blank chip or
as a recovery path.

## References

- TI SWRU283B - CC2544 System-on-Chip Solution for 2.4 GHz Applications
  User's Guide (the radio driver, USB core, and bootloader are all built
  directly against this).
- [mame82/munifying](https://github.com/mame82/munifying) - prior
  Logitech Unifying protocol research, referenced while working out the
  real radio configuration.
- [BastilleResearch/mousejack](https://github.com/BastilleResearch/mousejack)
  and [BastilleResearch/nrf-research-firmware](https://github.com/BastilleResearch/nrf-research-firmware) -
  the original MouseJack disclosure on Unifying dongle vulnerabilities.
- [xurubin/logitech_unifying_pid_patch](https://github.com/xurubin/logitech_unifying_pid_patch)
  and the [fwupd](https://github.com/fwupd/fwupd) Logitech HID++ plugin -
  referenced for the bootloader/runtime PID split and the HID++
  "enter bootloader" command.
- `logitech_stock_firmware/` in this repo - disassembly of the real
  Logitech firmware for this same chip (RQR24.07), done from scratch for
  this project.

## License

Published as-is, for educational and research use. No warranty of any
kind - use at your own risk. Author: [github.com/ferrets6].
