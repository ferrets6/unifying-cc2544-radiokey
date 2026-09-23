/* usb_hid.h - USB HID boot-keyboard interface on endpoint 1 (interrupt IN).
 *
 * See usb_hid.c for exact datasheet references (ch. 21 "USB Controller").
 */
#ifndef USB_HID_H
#define USB_HID_H

#include <stdint.h>

/* Initializes EP1 IN (max packet size, interrupt type). Call once at
 * startup, after usb_core_init(). */
void hid_init(void);

/* Builds a standard 8-byte boot-protocol keyboard report (byte0=
 * modifier, byte1=reserved/0, byte2..7=up to 6 keycodes, only the first
 * used here - one key at a time) and sends it on EP1 IN. keycode=0 = no
 * key (release report). Non-blocking: if the IN FIFO is still full (host
 * hasn't picked up the previous report), the report is queued (1 slot)
 * and sent by hid_poll() at the first opportunity. Must not be called
 * while hid_busy() - the queued report would be lost. */
void hid_send_report(uint8_t modifier, uint8_t keycode);

/* 1 while a report is still queued waiting for the IN FIFO to free up. */
uint8_t hid_busy(void);

/* Call continuously from the main loop (alongside usb_core_poll()): if a
 * report is queued and the IN FIFO has freed up, sends it. */
void hid_poll(void);

#endif
