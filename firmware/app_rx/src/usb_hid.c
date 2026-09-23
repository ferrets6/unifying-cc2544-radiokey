/* usb_hid.c - see usb_hid.h.
 *
 * USB registers for endpoints 1-5 (SWRU283B ch. 21 "USB Controller") -
 * share the same XREG addresses as USBCS0/USBCNT0 already used for EP0
 * in usb_core.c, with different meaning depending on USBINDEX (same
 * indexed-register pattern, here USBINDEX=1 instead of 0):
 *  - USBMAXI (0x6210): max IN packet size, in units of 8 bytes (not
 *    raw bytes) - an 8-byte report needs USBMAXI=1, not 8.
 *  - USBCS0/USBCSIL share address 0x6211: at USBINDEX=1, bit0 is
 *    INPKT_RDY (same logical meaning as USBCS0's bit1, different
 *    position), bit1=PKT_PRESENT (read-only, 1 if the IN FIFO has a
 *    packet queued).
 *  - USBCSIH (0x6212): bit7=AUTOSET (unused), bit6=ISO (0=bulk/
 *    interrupt, our case), bits5:4 reserved, always write "10",
 *    bit0=IN_DBL_BUF (0=no double buffering, not needed).
 *  - USBMAXO (0x6213): 0 for an IN-only endpoint.
 *  - USBF1 (0x6222): endpoint 1's dedicated FIFO (fixed address, not
 *    indexed by USBINDEX like USBF0/USBCS0/USBMAXI).
 */
#include "usb_hid.h"

#define XREG(addr) (*(volatile __xdata uint8_t *)(addr))

#define USBINDEX  XREG(0x620E) /* same register used in usb_core.c */
#define USBMAXI   XREG(0x6210)
#define USBCSIL   XREG(0x6211) /* == USBCS0 when USBINDEX=0, here USBINDEX=1 */
#define USBCSIH   XREG(0x6212)
#define USBMAXO   XREG(0x6213)
#define USBF1     XREG(0x6222) /* EP1 FIFO, fixed address */

#define USBCSIL_INPKT_RDY   0x01
#define USBCSIL_PKT_PRESENT 0x02

/* Each report is an event (one key down or up), so none may be dropped
 * or reordered. While the IN FIFO still holds the previous report (the
 * host only drains it every bInterval=10ms) the new one waits here, and
 * hid_busy() stays true until hid_poll() hands it to the FIFO - the
 * caller must not submit another report meanwhile (app_rx/main.c
 * stops reading the radio instead, so backpressure reaches the TX). */
static uint8_t pending_report[8];
static uint8_t report_pending;

static void hid_write_report(const uint8_t *report)
{
    uint8_t i;
    USBINDEX = 1;
    for (i = 0; i < 8; i++) {
        USBF1 = report[i];
    }
    USBCSIL = USBCSIL_INPKT_RDY;
}

void hid_init(void)
{
    USBINDEX = 1;
    USBMAXI = 1;   /* 1 * 8 bytes = 8, the boot-keyboard report size */
    USBMAXO = 0;   /* IN-only endpoint */
    USBCSIH = 0x20; /* bits5:4 = 10 (reserved, always this), ISO=0, AUTOSET=0, IN_DBL_BUF=0 */
}

void hid_send_report(uint8_t modifier, uint8_t keycode)
{
    uint8_t report[8];

    report[0] = modifier;
    report[1] = 0; /* reserved */
    report[2] = keycode;
    report[3] = 0;
    report[4] = 0;
    report[5] = 0;
    report[6] = 0;
    report[7] = 0;

    USBINDEX = 1;
    if (USBCSIL & USBCSIL_PKT_PRESENT) {
        uint8_t i;
        for (i = 0; i < 8; i++) {
            pending_report[i] = report[i];
        }
        report_pending = 1;
        return;
    }
    hid_write_report(report);
}

uint8_t hid_busy(void)
{
    return report_pending;
}

void hid_poll(void)
{
    if (!report_pending) {
        return;
    }
    USBINDEX = 1;
    if (USBCSIL & USBCSIL_PKT_PRESENT) {
        return; /* still full, retry next round */
    }
    report_pending = 0;
    hid_write_report(pending_report);
}
