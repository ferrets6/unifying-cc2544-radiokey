#!/usr/bin/env python3
"""EXPERIMENTAL: forwards real key presses from a physical keyboard
plugged into this machine (Raspberry Pi) to the app_tx dongle via
SEND_KEY, one radio packet per press/release - a first draft of "real
keyboard input on the TX side" (see TODO.md).

Requires python3-evdev (`sudo apt install python3-evdev` or
`pip3 install evdev`) and read access to /dev/input/eventX - run as
root (sudo) unless your user is in the `input` group.

Only a small set of keys is mapped for now (letters, digits, enter,
esc, backspace, tab, space, arrows, -/=, and the 4 standard
modifiers) - extend KEY_MAP as needed.

Exit: hold Ctrl+Alt+Esc together. NOT Ctrl+C - that's caught by the
terminal running this script and kills it before it reaches the event
loop, so it can never be forwarded as a real Ctrl+C keystroke anyway.
Fine for now since this is a draft; a real input method will need a
different approach (e.g. a dedicated "send" hotkey scheme).

Usage: sudo python3 keyboard_forward.py [event_device]
<event_device> (e.g. /dev/input/event3) is optional - if omitted,
lists available keyboard-like devices and asks which one.
"""
import os
import sys

from evdev import InputDevice, categorize, ecodes, list_devices

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
import usb_select

VID, PID = 0x1209, 0x0030
SEND_KEY = 0x13

KEY_MAP = {
    ecodes.KEY_A: 0x04, ecodes.KEY_B: 0x05, ecodes.KEY_C: 0x06, ecodes.KEY_D: 0x07,
    ecodes.KEY_E: 0x08, ecodes.KEY_F: 0x09, ecodes.KEY_G: 0x0A, ecodes.KEY_H: 0x0B,
    ecodes.KEY_I: 0x0C, ecodes.KEY_J: 0x0D, ecodes.KEY_K: 0x0E, ecodes.KEY_L: 0x0F,
    ecodes.KEY_M: 0x10, ecodes.KEY_N: 0x11, ecodes.KEY_O: 0x12, ecodes.KEY_P: 0x13,
    ecodes.KEY_Q: 0x14, ecodes.KEY_R: 0x15, ecodes.KEY_S: 0x16, ecodes.KEY_T: 0x17,
    ecodes.KEY_U: 0x18, ecodes.KEY_V: 0x19, ecodes.KEY_W: 0x1A, ecodes.KEY_X: 0x1B,
    ecodes.KEY_Y: 0x1C, ecodes.KEY_Z: 0x1D,
    ecodes.KEY_1: 0x1E, ecodes.KEY_2: 0x1F, ecodes.KEY_3: 0x20, ecodes.KEY_4: 0x21,
    ecodes.KEY_5: 0x22, ecodes.KEY_6: 0x23, ecodes.KEY_7: 0x24, ecodes.KEY_8: 0x25,
    ecodes.KEY_9: 0x26, ecodes.KEY_0: 0x27,
    ecodes.KEY_ENTER: 0x28, ecodes.KEY_ESC: 0x29, ecodes.KEY_BACKSPACE: 0x2A,
    ecodes.KEY_TAB: 0x2B, ecodes.KEY_SPACE: 0x2C, ecodes.KEY_MINUS: 0x2D,
    ecodes.KEY_EQUAL: 0x2E,
    ecodes.KEY_RIGHT: 0x4F, ecodes.KEY_LEFT: 0x50, ecodes.KEY_DOWN: 0x51,
    ecodes.KEY_UP: 0x52,
}

MODIFIER_KEYS = {
    ecodes.KEY_LEFTCTRL: 0x01, ecodes.KEY_LEFTSHIFT: 0x02,
    ecodes.KEY_LEFTALT: 0x04, ecodes.KEY_LEFTMETA: 0x08,
    ecodes.KEY_RIGHTCTRL: 0x10, ecodes.KEY_RIGHTSHIFT: 0x20,
    ecodes.KEY_RIGHTALT: 0x40, ecodes.KEY_RIGHTMETA: 0x80,
}

EXIT_COMBO = {ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTALT, ecodes.KEY_ESC}


def pick_device(explicit):
    if explicit:
        return InputDevice(explicit)
    candidates = [InputDevice(p) for p in list_devices()]
    keyboards = [d for d in candidates if ecodes.EV_KEY in d.capabilities()
                 and ecodes.KEY_A in d.capabilities()[ecodes.EV_KEY]]
    if not keyboards:
        print("No keyboard-like /dev/input/eventX found")
        sys.exit(1)
    if len(keyboards) == 1:
        return keyboards[0]
    print("Available keyboard-like devices:")
    for i, d in enumerate(keyboards):
        print(f" {i + 1}) {d.path} - {d.name}")
    while True:
        choice = input("which one? > ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(keyboards):
                return keyboards[idx]
        except ValueError:
            pass
        print("invalid choice")


def main():
    explicit = sys.argv[1] if len(sys.argv) > 1 else None
    dev_in = pick_device(explicit)
    print(f"reading from {dev_in.path} ({dev_in.name})")

    dev_out = usb_select.select_device(VID, PID, prompt_label="pick the app_tx dongle")
    if dev_out is None:
        print(f"dongle 1209:{PID:04x} not found")
        sys.exit(1)
    try:
        dev_out.set_configuration()
    except Exception:
        pass

    pressed_mod = 0
    held = set()
    dev_in.grab()
    print("forwarding keys - hold Ctrl+Alt+Esc together to quit")
    try:
        for event in dev_in.read_loop():
            if event.type != ecodes.EV_KEY:
                continue
            key = categorize(event)
            code = key.scancode
            down = key.keystate in (key.key_down, key.key_hold)

            if down:
                held.add(code)
            else:
                held.discard(code)
            if EXIT_COMBO <= held:
                break
            if key.keystate == key.key_hold:
                continue

            if code in MODIFIER_KEYS:
                bit = MODIFIER_KEYS[code]
                pressed_mod = (pressed_mod | bit) if down else (pressed_mod & ~bit)
                continue

            if code not in KEY_MAP:
                continue
            kc = KEY_MAP[code]
            wValue = (pressed_mod << 8) | kc
            dev_out.ctrl_transfer(0x40, SEND_KEY, wValue, 0, bytes([1 if down else 0]))
    finally:
        dev_in.ungrab()
        print("\nstopped")


if __name__ == '__main__':
    main()
