# Debug interface tools (RST/DC/DD, `CCDebugger`)

Everything that talks to the chip over the 2-wire debug interface
instead of USB. Needed for a blank chip (no bootloader yet) or to
rewrite the bootloader itself. For everything else (app area, updates
when a working USB bootloader is already present) use the USB scripts
in `firmware/tools/` instead.

## Read-only tools

- **`get_chip_id.c`**: reads `CHIPID`/`CHVER`, no erase/write.
  ```
  gcc -Wall -o get_chip_id get_chip_id.c CCDebugger.c -lwiringPi
  sudo ./get_chip_id                # default pins (24/27/28)
  sudo ./get_chip_id -r 0 -c 1 -d 3  # different wiring
  ```
- **`cc_reset_only.c`**: reset only, no erase/write.
- **`dump_all_via_debug.c`** (build with `-O2`, otherwise the ~35KB
  bit-level read takes minutes): dumps ID/status, XREG, SFR mirror,
  factory info page, and the full 32KB flash to binary files - used to
  compare two chips byte-for-byte.

## Flash-writing tools

Each tool has a fixed address range and refuses to write outside it:

- **`erase_chip_via_debug.c`**: erases the **entire** chip.
- **`erase_bootloader_page_via_debug.c`**: erases **only** page 0
  (0x0000-0x03FF).
- **`erase_page_via_debug.c -p <page>`**: erases **only** the given app
  page (1024 bytes, same unit as `PAGE_SIZE` in `flash_firmware.py`) -
  rejects page 0.
- **`write_bootloader_via_debug.c`**: writes **only** page 0, rejects
  any byte at 0x0400+.
- **`write_app_via_debug.c`**: writes **only** the app area (addresses
  from the file itself, >= 0x0400), rejects any byte below 0x0400.
  Prompts to jump into the app after writing (no real reset from debug
  ever reaches the app - see below).

```
gcc -o erase_chip_via_debug erase_chip_via_debug.c CCDebugger.c -lwiringPi
gcc -o erase_bootloader_page_via_debug erase_bootloader_page_via_debug.c CCDebugger.c -lwiringPi
gcc -o erase_page_via_debug erase_page_via_debug.c CCDebugger.c -lwiringPi
gcc -o write_bootloader_via_debug write_bootloader_via_debug.c CCDebugger.c -lwiringPi
gcc -o write_app_via_debug write_app_via_debug.c CCDebugger.c -lwiringPi
```

Two Python wrappers combine erase+write in one command (build the C
tools above first):
- `flash_bootloader_page_via_debug.py [bootloader.ihx]`
- `flash_app_via_debug.py <file.ihx>` (computes and erases only the
  pages the file needs; rejects files with bytes below 0x0400)

`check_bootloader_via_debug.py` reads page 0 back and diffs it against
`firmware/bootloader/bin/bootloader.ihx`.

### Bootstrapping a blank chip

```
sudo ./erase_chip_via_debug
sudo ./write_bootloader_via_debug ../bootloader/bin/bootloader.ihx
sudo python3 flash_app_via_debug.py ../app_tx/bin/app_tx.ihx
```
Once the bootloader is present, prefer `firmware/tools/flash_firmware.py`
over debug for the app area - same result, no clip needed. Debug stays
necessary only for the bootloader itself (no USB command can rewrite
page 0 without going through `bootloader_updater`, see
`firmware/tools/update_bootloader.py`) or for a chip with no bootloader
yet.

Writing a third-party firmware (e.g. stock Logitech) to the app area
while keeping our bootloader works the same way: erase only the pages
it needs, write with `write_app_via_debug`. There's no way back to the
original Logitech bootloader - we don't have a copy, ours must stay in
page 0.

### No real reset ever reaches the app from debug

`cc_reset()` (or any debug-triggered reset) always reads as an external
`RESET_N` to the bootloader, never as power-on - so it always lands in
the bootloader's listening window, not the app. `write_app_via_debug`
works around this by injecting `LJMP 0x0400` directly via the debug
interface and resuming execution, when asked to.

## Pin-set reliability

The default pins (RST=24, DC=27, DD=28) are reliable. On a different
pin-set, long chunked writes can silently deposit zeroes - a
signal/wiring issue specific to that pin-set, not the code. Test on a
throwaway page (e.g. the last one, page 31) before trusting a new
pin-set.

## CPU vs. DMA

Flash writes use the CPU method - the dev chip's write DMA is damaged.
`ram_flash_write_dma.c` is the untested DMA variant.
