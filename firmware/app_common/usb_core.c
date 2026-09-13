/* usb_core.c - see usb_core.h.
 *
 * XREG addresses identical to (and proven working in)
 * firmware/bootloader/bootloader.asm.
 */
#include "usb_core.h"

#define XREG(addr) (*(volatile __xdata uint8_t *)(addr))

#define CLKCONCMD XREG(0x70C6)
#define CLKCONSTA XREG(0x709E)
#define USBADDR   XREG(0x6200)
#define USBINDEX  XREG(0x620E)
#define USBCTRL   XREG(0x620F)
#define USBCS0    XREG(0x6211)
#define USBCNT0   XREG(0x6216)
#define USBF0     XREG(0x6220)
#define TR0       XREG(0x624B)

__sfr __at(0xC9) WDCTL; /* watchdog, direct SFR - see SOFT_RESET in usb_core_poll() */
__sfr __at(0x9D) SLEEPSTA; /* last reset cause, bit 4:3 = RST[1:0] - see GET_LAST_RESET_CAUSE */
#define CLD XREG(0x6290) /* Clock-Loss Detector, bit0=EN - see usb_core_init() */

/* USBCS0 bits used (same meaning as bootloader.asm) */
#define USBCS0_OUTPKT_RDY   0x01
#define USBCS0_INPKT_RDY    0x02  /* read: "still transmitting" while high after INPKT_RDY */
#define USBCS0_SEND_STALL   0x20
#define USBCS0_DATA_END     0x08
#define USBCS0_CLR_OUTPKT_RDY 0x40

static void delay_loop(uint16_t n) {
    volatile uint16_t i;
    for (i = 0; i < n; i++) {
        ;
    }
}

/* Emergency watchdog: armed once here with MODE=10 (watchdog mode) and
 * INT=00 (longest interval, ~1s). Once in watchdog mode it can't be
 * disarmed or reconfigured until the next real reset, so it's armed
 * exactly once, here, and only ever fed (watchdog_feed()) or
 * deliberately left to expire (SOFT_RESET, below). If the app hangs for
 * any reason it stops feeding it by accident and the chip resets itself
 * within 1s - the bootloader (SLEEPSTA.RST==10) sees the cause and
 * opens its listening window instead of jumping back into a hung app. */
#define WDCTL_ARM  0x08 /* MODE=10, INT=00 (~1s) */
#define WDCTL_CLR1 0xA8 /* CLR=1010, rest=already-armed config */
#define WDCTL_CLR2 0x58 /* CLR=0101, within one watchdog clock period of the previous write */

static void watchdog_feed(void) {
    WDCTL = WDCTL_CLR1;
    WDCTL = WDCTL_CLR2;
}

/* Last reset cause (SLEEPSTA.RST[1:0]), captured once at boot - see
 * GET_LAST_RESET_CAUSE in usb_core_poll(). Read-only, reflects only the
 * last real reset (unaffected by APP_RESTART, a software jump), so it
 * must be read as early as possible in this function, before anything
 * else. */
static uint8_t last_reset_cause;

void usb_core_init(void) {
    /* The chip has five reset causes (SWRU283B ch. 5) but only four are
     * distinguishable via SLEEPSTA.RST - "a BOD reset is read as a POR
     * reset" (5.1), so a brownout and a real power-on are
     * indistinguishable (`00` either way). The Clock-Loss Detector
     * exists to diagnose an otherwise invisible cause ("can be used in
     * safety-critical systems to detect that the XOSC clock source has
     * stopped", 5.2) but is disabled after every reset by default:
     * without re-enabling it, a real clock fault shows up only as an
     * indefinite CPU hang eventually resolved by the emergency
     * watchdog, identical to (and indistinguishable from) a real
     * software hang (`SLEEPSTA.RST=10` either way). Must be re-enabled
     * every boot. Requires the 32MHz XOSC as system clock (5.2) -
     * CLKCONCMD=0x80 below selects it, so enabling happens after the
     * clock switch is confirmed via CLKCONSTA. */
    last_reset_cause = (SLEEPSTA >> 3) & 0x03;

    /* force a clean USB disconnect: the bootloader leaves the
     * peripheral enumerated as itself - without this the host would
     * never re-enumerate with our descriptors. */
    USBCTRL = 0x00;
    delay_loop(20000);

    /* same clock/PLL init sequence as bootloader.asm's _start */
    CLKCONCMD = 0x80;
    while (CLKCONSTA != 0x80) {
        ;
    }

    CLD = 0x01; /* re-enable the Clock-Loss Detector, see above */

    USBCTRL = 0x03;
    TR0 &= 0xFB;
    while (!(USBCTRL & 0x80)) {
        ;
    }
    USBCTRL |= 0x08;

    USBADDR = 0x00;

    WDCTL = WDCTL_ARM;
}

uint8_t usb_core_last_reset_cause(void) {
    return last_reset_cause;
}

void usb_ep0_ack(void) {
    USBINDEX = 0;
    USBCS0 = USBCS0_CLR_OUTPKT_RDY | USBCS0_DATA_END;
}

/* Responses longer than bMaxPacketSize0 (32 bytes - e.g. app_rx's 34-
 * byte HID config descriptor) get split across multiple IN
 * transactions, DATA_END only on the last (or on a short/empty packet
 * signaling the end) - USB doesn't allow a single IN packet longer than
 * the endpoint's max size. */
void usb_ep0_send(const uint8_t *data, uint8_t len) {
    uint8_t chunk, i;

    USBINDEX = 0;
    USBCS0 = USBCS0_CLR_OUTPKT_RDY; /* ack the SETUP, no OUT phase for an IN request */

    do {
        chunk = (len > 32) ? 32 : len;
        for (i = 0; i < chunk; i++) {
            USBF0 = data[i];
        }
        data += chunk;
        len = (uint8_t)(len - chunk);

        USBINDEX = 0;
        if (chunk == 32) {
            USBCS0 = USBCS0_INPKT_RDY; /* full packet: more bytes follow, not the last */
        } else {
            USBCS0 = USBCS0_INPKT_RDY | USBCS0_DATA_END; /* short (or empty) packet: end of transfer */
        }
        while (USBCS0 & USBCS0_INPKT_RDY) {
            ;
        }
    } while (chunk == 32);
}

/* usb_core_poll() reads the 8 SETUP bytes directly from USBF0 but
 * doesn't clear OUTPKT_RDY before calling the handler (the other paths
 * - usb_ep0_ack/usb_ep0_send/usb_ep0_stall - do that themselves as
 * their first step). An OUT data phase must therefore explicitly
 * consume that leftover flag first, before waiting for the real
 * OUTPKT_RDY of the data phase, otherwise it reads the SETUP bytes
 * again. */
uint8_t usb_ep0_recv(uint8_t *buf, uint8_t maxlen) {
    uint8_t cnt, i;
    USBINDEX = 0;
    USBCS0 = USBCS0_CLR_OUTPKT_RDY; /* consume the SETUP, then wait for the real OUT phase */
    while (!(USBCS0 & USBCS0_OUTPKT_RDY)) {
        ;
    }
    cnt = USBCNT0;
    if (cnt > maxlen) {
        cnt = maxlen;
    }
    for (i = 0; i < cnt; i++) {
        buf[i] = USBF0;
    }
    /* discard any bytes beyond maxlen (shouldn't happen with our
     * requests, all a few bytes, but just in case) */
    for (; i < USBCNT0; i++) {
        (void)USBF0;
    }
    USBCS0 = USBCS0_CLR_OUTPKT_RDY | USBCS0_DATA_END;
    return cnt;
}

void usb_ep0_stall(void) {
    USBINDEX = 0;
    USBCS0 = USBCS0_CLR_OUTPKT_RDY;
    USBCS0 = USBCS0_SEND_STALL;
}

static void handle_get_descriptor(uint8_t wValueL, uint8_t wValueH, uint8_t wLengthL, uint8_t wLengthH) {
    __code const uint8_t *desc;
    uint8_t len;

    if (wValueH == 0x01) {
        desc = device_descriptor;
        len = 18;
    } else if (wValueH == 0x02) {
        desc = config_descriptor;
        len = config_descriptor_len;
    } else if (wValueH == 0x03) {
        /* STRING descriptor - index 0 = LANGID list, 1 = manufacturer,
         * 2 = product. Stalls cleanly if the app provides no string
         * (length 0). */
        if (wValueL == 0) {
            desc = string_lang_descriptor;
            len = 4;
        } else if (wValueL == 1 && string_manufacturer_len > 0) {
            desc = string_manufacturer;
            len = string_manufacturer_len;
        } else if (wValueL == 2 && string_product_len > 0) {
            desc = string_product;
            len = string_product_len;
        } else {
            USBINDEX = 0;
            USBCS0 = USBCS0_CLR_OUTPKT_RDY;
            USBCS0 = USBCS0_SEND_STALL;
            return;
        }
    } else {
        /* not device/config/string: let the app try (e.g. HID/Report
         * for app_rx) - stall if unrecognized. */
        if (usb_app_get_descriptor(wValueH, wLengthL, wLengthH)) {
            return;
        }
        USBINDEX = 0;
        USBCS0 = USBCS0_CLR_OUTPKT_RDY;
        USBCS0 = USBCS0_SEND_STALL;
        return;
    }

    /* honor wLength: the host often asks for only the first 8 bytes of
     * the device descriptor (to read bMaxPacketSize0 before
     * SET_ADDRESS) - always answering with the full descriptor sends
     * extra bytes on the bus and desyncs EP0 state, breaking
     * enumeration. usb_ep0_send() splits into multiple packets on its
     * own if len > 32. */
    if (wLengthH == 0 && wLengthL < len) {
        len = wLengthL;
    }
    usb_ep0_send(desc, len);
}

void usb_core_poll(void) {
    uint8_t bmRequestType, bRequest, wValueL, wValueH, wIndexL, wIndexH, wLengthL, wLengthH;

    watchdog_feed();

    USBINDEX = 0;
    if (!(USBCS0 & USBCS0_OUTPKT_RDY)) {
        return;
    }

    /* read the 8 SETUP bytes (same order as bootloader.asm) */
    bmRequestType = USBF0;
    bRequest      = USBF0;
    wValueL       = USBF0;
    wValueH       = USBF0;
    wIndexL       = USBF0;
    wIndexH       = USBF0;
    wLengthL      = USBF0;
    wLengthH      = USBF0;

    if ((bmRequestType & 0x60) == 0x40) {
        if (bRequest == 0x04) {
            /* SOFT_RESET: the watchdog is already armed by
             * usb_core_init() with a fixed interval and can't be
             * reconfigured. This command just stops feeding it: the
             * chip resets itself within ~1s, same cause
             * (SLEEPSTA.RST==10, watchdog) the bootloader also sees for
             * a real accidental hang. Ack before blocking, so the host
             * sees the transaction complete cleanly before the chip
             * disappears from the bus. */
            USBCS0 = USBCS0_CLR_OUTPKT_RDY | USBCS0_DATA_END;
            while (1) {
                ;
            }
        }
        if (bRequest == 0x05) {
            /* APP_RESTART: restarts the app without ever going through
             * the bootloader - jumps straight to 0x0400. Not a real
             * hardware reset (SLEEPSTA.RST unaffected, read-only), but
             * re-runs full app init (radio/USB), real USB disconnect/
             * reconnect included. Ack before jumping, same order as
             * SOFT_RESET. Never returns (a jump, not a real call). */
            USBCS0 = USBCS0_CLR_OUTPKT_RDY | USBCS0_DATA_END;
            ((void (*)(void))0x0400)();
        }
        if (bRequest == 0x06) {
            /* GET_LAST_RESET_CAUSE: 1 byte, SLEEPSTA.RST[1:0] captured
             * at boot (see usb_core_init()). */
            uint8_t cause = usb_core_last_reset_cause();
            usb_ep0_send(&cause, 1);
            return;
        }
        if (bRequest == 0x07) {
            /* GET_APP_DUMP: reads up to 32 bytes from CODE space
             * starting at the 16-bit address in wValue - read-only, no
             * range restriction (a read can't corrupt anything). Used
             * to back up the running app before a bootloader update
             * (bootloader_updater overwrites the whole app area) - see
             * firmware/tools/dump_app.py. */
            uint16_t addr = ((uint16_t)wValueH << 8) | wValueL;
            uint8_t len = wLengthL;
            __code uint8_t *src = (__code uint8_t *)addr;
            if (len > 32) {
                len = 32;
            }
            usb_ep0_send(src, len);
            return;
        }
        /* Type = Vendor: delegate to the app */
        usb_vendor_request(bRequest, wValueL, wValueH, wIndexL, wIndexH, wLengthL, wLengthH);
        return;
    }

    /* minimal standard requests, same subset as the bootloader:
     * GET_DESCRIPTOR (0x06), SET_ADDRESS (0x05), SET_CONFIGURATION (0x09) */
    if (bRequest == 0x06) {
        handle_get_descriptor(wValueL, wValueH, wLengthL, wLengthH);
        return;
    }
    if (bRequest == 0x05) {
        USBCS0 = USBCS0_CLR_OUTPKT_RDY | USBCS0_DATA_END;
        USBADDR = wValueL & 0x7F;
        return;
    }
    if (bRequest == 0x09) {
        USBCS0 = USBCS0_CLR_OUTPKT_RDY | USBCS0_DATA_END;
        return;
    }

    usb_ep0_stall();
}
