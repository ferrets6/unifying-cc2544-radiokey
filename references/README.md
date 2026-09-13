# TI CC2544 references

- `cc2544_datasheet.pdf` - TI SWRS103D data sheet. The only document
  with the real physical pinout (QFN32, Table 1): pin 1 = USB_P (D+),
  pin 2 = USB_N (D-), pin 15 = RESET_N, P1_2/P1_3 (pins 28/29) = debug
  clock/data.
- `swru283b.pdf` - TI SWRU283B User's Guide (registers, RF core, USB,
  flash controller, debug interface). No physical pinout, despite the
  similar name.
- `pages/` - selected pages pre-rendered as PNG for quick reference
  (`pdftoppm -png -r 200 -f N -l N swru283b.pdf pages/name-N`): pinout,
  PRF register tables, RX task state machine, `SW_CONF`, `PRF_ENDCAUSE`
  values.
