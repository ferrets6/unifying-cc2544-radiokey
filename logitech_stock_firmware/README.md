# Stock Logitech firmware (RQR24.07) - reference material

`RQR24.07_B0030.shex`, downloaded from
[`Logitech/fw_updates`](https://github.com/Logitech/fw_updates)
(`RQR24/RQR24.07/RQR24.07_B0030.shex`), is a signed application-update
image for the same dongle (USB `046D:C52B`, bootloader `BOT03 >= 02`).
It contains no bytes below 0x0400 - Logitech update images never touch
the bootloader partition, only the app.

`strip_signature.py` removes the non-standard trailing block (record
type `0xFD` after a type-5 record, almost certainly the signature) with
no other change, producing a file that still starts at 0x0400 and is
safe to flash with `write_app_via_debug`/`flash_firmware.py` alongside
our own bootloader.

## Interrupt vectors

The real firmware relocates all 18 interrupt vectors (not just reset)
to `+0x400`, and expects forwarding stubs at the 18 real hardware
vector addresses (`0x0003, 0x000B, ... 0x008B`, 8-byte stride) - on a
genuine dongle, provided by the real Logitech bootloader (BOT03). Our
bootloader provides the same 18 stubs (`inject_vectors_min.py`, see
`firmware/bootloader/README.md`), so this should already work without
any change to the stock firmware file. If it doesn't, the fix belongs
in our bootloader, never in the app file - low memory (below 0x0400)
belongs to the bootloader.

## Files

- `RQR24.07_B0030.shex` - original signed download.
- `disasm8051.py` / `indep_disasm.py` - two independently written 8051
  disassemblers (no ready-made tool was available), used to
  cross-check each other.
- `full_disasm.txt` - full disassembly output, used as ground truth for
  the real radio/USB register values now in `firmware/app_common/`.
- `enter_bootloader.py` - HID++ command to make a stock receiver enter
  its firmware-update mode (see `COMMANDS.md`).

## Findings used in this project's firmware

- USB init order differs from the datasheet: `USBCTRL |= 0x03`
  (USB_EN+PLL_EN together) **before** clearing `TR0.USB_PAD_PD`, then
  poll `USBCTRL.PLL_LOCKED`.
- Radio config (Auto Mode): `FRMCTRL0=0x43`, `MDMCTRL0=0x0E` (2Mbps
  GFSK), `MDMCTRL2=0xCC`, CRC-16-CCITT (`BSP_P0-3=00 00 21 10`,
  `PRF_CRC_LEN=0x02`), `PRF_TASK_CONF=0x86` (Auto Mode). All already
  applied in `firmware/app_common/radio.c`.
- Sync word (`SW0-3`) is copied at runtime from a per-device pairing
  buffer, not hardcoded - confirms our static-at-boot approach is
  structurally correct.
- Radio channel table (24 channels) at ROM `0x0BFE-0x0C15`.
