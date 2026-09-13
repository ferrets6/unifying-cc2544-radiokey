# Flashing from Windows

The Python tools in `firmware/tools/` are pure pyusb, no Linux-specific
code - they work identically on Windows. The only thing missing is a
generic USB driver: without one, Windows shows the dongle as unknown
(`Status: Error`) and libusb can't see it either.

(`firmware/debug/get_chip_id` and the other debug-clip tools are
Raspberry Pi only - GPIO access. Not needed on Windows: entering the
bootloader is always done via `SOFT_RESET` over USB, see `COMMANDS.md`.)

## 1. Python + pyusb

```powershell
python -m pip install pyusb libusb-package
```

## 2. WinUSB driver (Zadig)

Windows treats each VID:PID as a separate device, so install the driver
for each PID our dongles can present:

- `1209:0010` - bootloader (listens indefinitely after a reset/`SOFT_RESET`)
- `1209:0020` - `bootloader_updater`
- `1209:0030` - `app_tx`/`app_rx` (share this PID)

Note: `app_rx` is a HID keyboard, recognized natively by Windows with no
driver - installing WinUSB on `0030` for `app_tx` while both are
attached is not verified not to interfere with `app_rx`'s HID
recognition (see `TODO.md`).

Steps:
1. Download [Zadig](https://zadig.akeo.ie/), run as administrator.
2. Options -> **List All Devices**.
3. Find the dongle by VID/PID (shown as a generic name) - double-check
   the exact `USB ID` before proceeding.
4. Driver: **WinUSB**, then **Install Driver**.
5. Repeat for each PID you need from this PC.

The driver stays assigned to that PID across sessions.

## 3. Verify

```powershell
python -c "import usb.core, libusb_package; d = usb.core.find(idVendor=0x1209, idProduct=0x0030, backend=libusb_package.get_libusb1_backend()); print('found' if d else 'NOT found')"
```

## 4. Using the scripts

Same commands as on the Pi:
```powershell
python firmware\tools\flash_firmware.py firmware\app_tx\bin\app_tx.ihx
```

## Audible USB connect/disconnect with no driver installed

Windows periodically retries automatic driver installation for unknown
devices - not a spontaneous firmware reboot. Installing the WinUSB
driver (step 2) makes it stop.
