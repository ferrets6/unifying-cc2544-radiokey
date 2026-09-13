# Dongle <-> USB port <-> debug pins

Reference to avoid mixing up the two dongles. The "#1"/"#2" labels in
`images/pi2_wiring_diagram_dual.jpg` only say which Pi GPIO pin-set is
wired to which chip electrically - not which USB dongle (port, PID) is
behind it. Always verify live (`get_chip_id`, which forces a reset and
shows which port's disconnect/reconnect appears in `dmesg`), don't
assume.

| | Dongle A | Dongle B |
|---|---|---|
| USB port (`lsusb -t` / `dmesg`) | `1-1.4` | `1-1.5` |
| Debug pin-set (diagram) | "#2" | "#1" |
| `get_chip_id` pins | `-r 0 -c 1 -d 3` | `-r 24 -c 27 -d 28` (default) |
| Current firmware | `app_rx` | `app_tx` |
| Chip | CC2544, CHVER 0x14 | CC2544, CHVER 0x14 |

Recheck this table before any debug-clip reset or single-dongle reflash,
and whenever the physical wiring changes.
