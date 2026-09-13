# USB vendor commands

Per-component PID: bootloader = `1209:0010`, `bootloader_updater` =
`1209:0020`, `app_tx`/`app_rx` = `1209:0030` (distinguished from each
other only by `iProduct`, not PID).

## `app_tx`/`app_rx` (PID `0030`)

Implemented in the shared USB core (`firmware/app_common/usb_core.c`),
handled before any app-specific logic.

### `SOFT_RESET` (`bRequest=0x04`) - reboot into the bootloader

OUT, no data. Stops feeding the emergency watchdog (armed by
`usb_core_init()`, ~1s). The chip resets itself (`SLEEPSTA.RST=10`,
watchdog) and the bootloader opens its indefinite listening window. Use
only to update firmware - a real hang triggers the same watchdog on its
own.

```python
dev = usb.core.find(idVendor=0x1209, idProduct=0x0030)
dev.ctrl_transfer(0x40, 0x04, 0, 0, None, timeout=1000)
```

### `APP_RESTART` (`bRequest=0x05`) - reboot without the bootloader

OUT, no data. Jumps straight to `0x0400` - not a real hardware reset
(`SLEEPSTA.RST` is read-only and unaffected), but re-runs full app init
(`usb_core_init()` + `radio_init()`), real USB disconnect/reconnect
included. Useful to reset app state (e.g. the radio) without entering
update mode.

```python
dev.ctrl_transfer(0x40, 0x05, 0, 0, None, timeout=1000)
```
The host sometimes sees a `Pipe error` on the ack (cosmetic - the jump
happens before the host observes a clean transaction end); check
`dmesg` for the disconnect/reconnect instead.

### `GET_LAST_RESET_CAUSE` (`bRequest=0x06`, IN 1 byte)

Returns `SLEEPSTA.RST[1:0]` captured once at boot: `00` = power-on or
brownout (indistinguishable, SWRU283B 5.1), `01` = external `RESET_N`,
`10` = watchdog (real hang or deliberate `SOFT_RESET`), `11` =
clock-loss. Unaffected by `APP_RESTART`.

```python
cause = dev.ctrl_transfer(0xC0, 0x06, 0, 0, 1, timeout=2000)[0]
```

`usb_core_init()` also re-enables the Clock-Loss Detector (`CLD.EN`,
XREG `0x6290`) every boot - disabled by default after any reset
(SWRU283B ch. 5), otherwise a real clock fault would be
indistinguishable from a plain watchdog hang.

### `GET_APP_DUMP` (`bRequest=0x07`, IN up to 32 bytes)

Read-only dump of CODE space starting at the 16-bit address in
`wValue`. Used by `firmware/tools/dump_app.py` to back up the running
app before a bootloader update (that path overwrites the whole app
area via `bootloader_updater`).

```python
data = bytes(dev.ctrl_transfer(0xC0, 0x07, 0x0400, 0, 32, timeout=1000))
```

## Stock Logitech receiver (VID:PID `046d:c52b`)

Standard HID++ 1.0 command (documented in fwupd's
`fu_logitech_hidpp_runtime_unifying_detach()`), written to the
receiver's own hidraw interface (not a paired child device):

```
10 FF 80 F0 49 43 50   # SHORT/RECEIVER/SET_REGISTER/DEVICE_FIRMWARE_UPDATE_MODE/"ICP"
```

```bash
sudo python3 logitech_stock_firmware/enter_bootloader.py /dev/hidraw0
```
A `BrokenPipeError` mid-write is expected (the command triggers an
immediate reset) and handled by the script.
