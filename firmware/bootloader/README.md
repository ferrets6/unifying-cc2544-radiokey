# Bootloader

`src/bootloader.asm` is the bootloader that actually runs on the
dongles, hand-written 8051 assembly. Compiled images are committed
under `bin/` - no need to rebuild just to flash.

## New chip vs. chip that already has our bootloader

- **New/blank chip** (still has the stock Logitech bootloader, or none
  at all): our bootloader isn't reachable over USB yet, so the scripts
  in `firmware/tools/` have nothing to talk to. Use the debug interface
  instead - see `firmware/debug/`. One-time step per chip.
- **Chip that already has our bootloader**: everything from here on
  goes over USB, via `firmware/tools/` - no debug needed, including for
  updating the bootloader itself again.

## The two components

```
src/bootloader.asm          -> bin/bootloader.ihx          the real bootloader, page 0 (0x0000-0x03FF)
src/bootloader_updater.asm  -> bin/bootloader_updater.ihx  disposable bridge used to rewrite the bootloader
```

- **`bootloader`** runs after every reset. Reads `SLEEPSTA.RST` to tell
  a real power-on (jumps straight to 0x0400, the current app) from any
  other cause (opens an indefinite USB listening window). Exposes a USB
  protocol to write a new firmware/app at 0x0400+ (`ERASE_PAGE`/
  `WRITE_CHUNK`/`FLASH_STARTED`/`FLASH_FINISHED`). Can't rewrite itself
  (no safe self-erase while executing from the same page).
- **`bootloader_updater`** exists for one reason: get loaded temporarily
  at 0x0400 (like any other app, via `bootloader` itself) so it can
  rewrite the real `bootloader` in page 0 from a different page. Gets
  overwritten by a real firmware/app once the update is done.

## Tools (`firmware/tools/`)

| Tool | Talks to | Purpose |
|---|---|---|
| `flash_firmware.py [file.ihx] [port]` | `bootloader` (PID `0010`) | Writes any firmware/app at 0x0400+. No argument: picks from `firmware/*/bin/`. Auto-resets a running app to reach the bootloader if needed. |
| `update_bootloader.py [bootloader.ihx] [port]` | orchestrates the full flow | Backs up the running app (if ours), loads `bootloader_updater`, writes+verifies the new bootloader, then reboots into the bootloader or restores the backed-up app. |
| `jump_to_app.py [port]` | `bootloader` (PID `0010`) | Jumps into the current app without writing anything (zero-length `FLASH_STARTED`/`FLASH_FINISHED`). |
| `dump_app.py [out.ihx] [port]` | `app_tx`/`app_rx` (PID `0030`) | Backs up the running app via `GET_APP_DUMP` - only works if it's our firmware. |
| `read_bootloader.py [addr] [n]` | `bootloader_updater` (PID `0020`) | Read-only page 0 dump/verification. |

## FLASH_STARTED / FLASH_FINISHED protocol

Implemented identically by `bootloader` and `bootloader_updater`.

- **`FLASH_STARTED`** (`bRequest=0x04`, `wValue`=total bytes about to be
  written): disables the startup window's timeout until
  `FLASH_FINISHED` arrives, so a write can't be interrupted mid-way
  regardless of size.
- **`FLASH_FINISHED`** (`bRequest=0x05`, IN 1 byte): compares bytes
  written against the declared length, returns `0x00` (OK) or `0x01`
  (mismatch), then jumps straight to the app.

`bootloader_updater` adds three commands restricted to page 0 only
(`ERASE_STAGE1`=`0x10`, `WRITE_STAGE1_CHUNK`=`0x11`, reject anything
outside 0x0000-0x03FF; `RESET_STAGE1`=`0x12`, real hardware reset via
watchdog, no debug clip needed), plus `READ_CHUNK` (`0x03`) for
byte-for-byte verification before reset.

Protocol state (`FLASHING_ACTIVE`, `EXPECTED_LEN_*`, `WRITTEN_LEN_*`)
must live in internal RAM, never XDATA: those XDATA addresses are used
by the RAM-resident flash-write routine copy - an XDATA write there
silently corrupts it (the write reports success but writes nothing
real).

## Building

Toolchain: `sdas8051`/`sdcc` (`sdcc` package on Debian/Raspbian).

```
cd src/
sdas8051 -los bootloader.rel bootloader.asm
sdcc -mmcs51 --code-loc 0x0090 --out-fmt-ihx -o bootloader_linked.ihx bootloader.rel
python3 inject_vectors_min.py bootloader_linked.ihx ../bin/bootloader.ihx
```
`inject_vectors_min.py` adds the reset vector and the 18 interrupt
vector forwarding stubs (real hardware vectors -> `0x0400+vector`) that
`bootloader.asm` doesn't include directly.

```
sdas8051 -los bootloader_updater.rel bootloader_updater.asm
sdcc -mmcs51 --code-loc 0x0400 --out-fmt-ihx -o ../bin/bootloader_updater.ihx bootloader_updater.rel
```

## CPU vs. DMA

Flash writes use the CPU method (byte-by-byte via `FWDATA`), not DMA -
the dev chip's write DMA is damaged. TI's datasheet (SWRU283B)
recommends DMA as the faster "preferred method"; see `firmware/debug/`
for the same tradeoff on the debug-interface tools.
