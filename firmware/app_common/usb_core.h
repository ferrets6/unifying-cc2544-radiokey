/* usb_core.h - EP0-only USB core shared by app_tx/app_rx.
 *
 * C port of the EP0 loop from firmware/bootloader/bootloader.asm (same
 * XREG registers, same USBCS0 bit meaning). No endpoint besides EP0 -
 * control transfers only, matching how the dongle actually enumerates
 * (1 vendor interface, 0 endpoints for app_tx; app_rx adds a HID
 * endpoint, see below).
 *
 * The app provides its own descriptors and implements
 * usb_vendor_request() for its own bRequest commands.
 */
#ifndef USB_CORE_H
#define USB_CORE_H

#include <stdint.h>

/* Provided by the app's main.c. app_tx uses the bootloader's minimal
 * scheme (1 vendor interface, 0 endpoints, 18 bytes total); app_rx adds
 * a HID boot-keyboard interface with EP1 IN (34 bytes total). */
extern __code const uint8_t device_descriptor[18];
extern __code const uint8_t config_descriptor[];
extern const uint8_t config_descriptor_len;

/* String descriptors (GET_DESCRIPTOR type 0x03), optional - give the
 * device a real name instead of "Unknown Device". Index 0 is the
 * required LANGID list, 1 = manufacturer, 2 = product. Unused if
 * device_descriptor's iManufacturer/iProduct are 0 (the host never
 * requests them). */
extern __code const uint8_t string_lang_descriptor[4];
extern __code const uint8_t string_manufacturer[];
extern const uint8_t string_manufacturer_len;
extern __code const uint8_t string_product[];
extern const uint8_t string_product_len;

/* Extension point for descriptors beyond device(0x01)/config(0x02) -
 * e.g. HID(0x21)/Report(0x22), requested as standard (not vendor)
 * GET_DESCRIPTOR by the host's HID stack. Apps that don't need it (e.g.
 * app_tx) return 0. Must handle ack/send/stall itself via the usb_ep0_*
 * helpers. Returns 1 if handled, 0 if not recognized (usb_core stalls
 * on its own in that case). */
uint8_t usb_app_get_descriptor(uint8_t wValueH, uint8_t wLengthL, uint8_t wLengthH);

/* Initializes USB clock/PLL and forces a clean USB disconnect/reconnect
 * (the bootloader leaves the peripheral enumerated as itself - without
 * this the host would keep seeing the old descriptor). Also arms the
 * emergency hardware watchdog (~1s, see usb_core.c). Call once at app
 * startup.
 *
 * Four vendor USB commands handled here, before any app-specific logic
 * - see COMMANDS.md for detail:
 *  - SOFT_RESET (bRequest 0x04): stops feeding the watchdog, the chip
 *    resets itself within ~1s into the bootloader's listening state.
 *    Use only to update firmware.
 *  - APP_RESTART (bRequest 0x05): jumps straight to 0x0400 without
 *    going through the bootloader - not a real hardware reset
 *    (SLEEPSTA.RST is read-only, unaffected), but re-runs full app init
 *    (USB+radio), real USB disconnect/reconnect included. Use to reset
 *    app state without entering update mode.
 *  - GET_LAST_RESET_CAUSE (bRequest 0x06, IN 1 byte): SLEEPSTA.RST[1:0]
 *    captured at boot - 00=power-on/brownout (indistinguishable,
 *    SWRU283B 5.1), 01=external RESET_N, 10=watchdog, 11=clock-loss.
 *    Also re-enables the Clock-Loss Detector (disabled by default after
 *    every reset, 5.2), otherwise a real clock fault reads identically
 *    to a plain software hang (both as 10, watchdog).
 *  - GET_APP_DUMP (bRequest 0x07, IN up to 32 bytes): reads CODE space
 *    from the 16-bit address in wValue - read-only. Used to back up the
 *    running app before a bootloader update, see
 *    firmware/tools/dump_app.py. */
void usb_core_init(void);

uint8_t usb_core_last_reset_cause(void);

/* Call continuously from main: polls EP0, feeds the emergency watchdog,
 * and dispatches vendor requests to usb_vendor_request(). */
void usb_core_poll(void);

/* Implemented by the app: handles its own vendor bRequests. Must
 * respond using the helpers below - call usb_ep0_stall() for anything
 * unrecognized. */
void usb_vendor_request(uint8_t bRequest, uint8_t wValueL, uint8_t wValueH,
                         uint8_t wIndexL, uint8_t wIndexH,
                         uint8_t wLengthL, uint8_t wLengthH);

/* Helpers for usb_vendor_request() handlers */
void usb_ep0_ack(void);                                   /* OUT with no data, or immediate command ack */
void usb_ep0_send(const uint8_t *data, uint8_t len);       /* IN phase, len <= wMaxPacketSize0 (32) */
uint8_t usb_ep0_recv(uint8_t *buf, uint8_t maxlen);        /* OUT phase, single packet (<=32 bytes), returns bytes read */
void usb_ep0_stall(void);

#endif
