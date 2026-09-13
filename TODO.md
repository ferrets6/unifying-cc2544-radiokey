# TODO

## Real keyboard input on the TX side (High)

This repo is a transport layer, not a keyboard: `app_rx` enumerates as a
real USB HID keyboard, but `app_tx` has no physical key input - a key
press only happens via a USB vendor command sent by hand
(`firmware/tools/interactive_commands.py`, `SEND_KEY`).

**To do**: something that takes "which key" as input and calls
`SEND_KEY` over USB - at minimum a small Python script/daemon exposing
this (e.g. one function call or a tiny local API), meant to be driven by
a separate frontend project (key capture/UI) later. Design TBD.

## Spontaneous reboots into the bootloader (High)

The dongle can end up in the bootloader on its own, no command sent. Not
the software watchdog (Auto Mode radio link and `APP_RESTART` are
verified reliable, see `firmware/app_common/radio.c`): one captured case
via `GET_LAST_RESET_CAUSE` showed `SLEEPSTA.RST=01`, external `RESET_N` -
a physical/electrical cause, not a software hang.

**Working theory, unconfirmed**: the debug clip's RST wire, used heavily
on these dongles, not fully disconnected/isolated during normal use. One
observed event hit both dongles at the same instant, more consistent
with a shared electrical cause than an independent software bug on two
separate chips.

**To do**: physically check RST wire isolation on both dongles (not
fixable in firmware). If it recurs, read `GET_LAST_RESET_CAUSE` before
any other action that causes a reset (`SOFT_RESET` or a flash overwrite
the historical value).

## Windows driver (Medium)

- Verify empirically whether `app_rx` (HID keyboard) still works
  normally if WinUSB gets installed on PID `0x0030` to control `app_tx`
  from a script, with both dongles attached together (they share that
  PID).
- WCID (automatic driver binding without Zadig) blocked by the
  bootloader's page-0 space budget (~4 bytes free) - revisit only if
  more room is freed up.

## Other

- **DMA vs CPU flash writes**: DMA never validated on a healthy chip
  (the dev unit's flash-write DMA is damaged). If a confirmed-healthy
  chip becomes available, port `firmware/debug/ram_flash_write_dma.c`
  (written but untested) into the same assembly style as
  `firmware/bootloader/src/bootloader.asm`.
