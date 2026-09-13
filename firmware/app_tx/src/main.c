/* app_tx - SEND_KEY vendor USB command sends a real keystroke event via
 * radio (see ../app_common/radio.c) to the app_rx dongle, which turns
 * it into a USB HID report. SEND_TEST_PACKET (diagnostic pattern) stays
 * available for testing the radio link alone. Enumerates as VID:PID
 * 0x1209:0x0030, PID split per component (bootloader=0x0010,
 * bootloader_updater=0x0020, app=0x0030).
 */
#include "../../app_common/usb_core.h"
#include "../../app_common/radio.h"

__code const uint8_t device_descriptor[18] = {
    18, 0x01, 0x10, 0x01, 0xFF, 0x00, 0x00, 32,
    0x09, 0x12, 0x30, 0x00, 0x00, 0x01, 1, 2, 0, 0x01 /* iManufacturer=1, iProduct=2 */
};

__code const uint8_t config_descriptor[18] = {
    9, 0x02, 18, 0, 1, 1, 0, 0x80, 50,
    9, 0x04, 0, 0, 0, 0xFF, 0x00, 0x00, 0
};
const uint8_t config_descriptor_len = 18;

/* String descriptors - see usb_core.h. Give the device a real name
 * instead of "Unknown Device". */
__code const uint8_t string_lang_descriptor[4] = { 0x04, 0x03, 0x09, 0x04 }; /* LANGID: English (US) */
__code const uint8_t string_manufacturer[] = {
    0x32, 0x03, 0x75, 0x00, 0x6E, 0x00, 0x69, 0x00, 0x66, 0x00, 0x79, 0x00, 0x69, 0x00,
    0x6E, 0x00, 0x67, 0x00, 0x2D, 0x00, 0x63, 0x00, 0x63, 0x00, 0x32, 0x00, 0x35, 0x00,
    0x34, 0x00, 0x34, 0x00, 0x2D, 0x00, 0x72, 0x00, 0x61, 0x00, 0x64, 0x00, 0x69, 0x00,
    0x6F, 0x00, 0x6B, 0x00, 0x65, 0x00, 0x79, 0x00 /* "unifying-cc2544-radiokey" */
};
const uint8_t string_manufacturer_len = sizeof(string_manufacturer);
__code const uint8_t string_product[] = {
    0x24, 0x03, 0x55, 0x00, 0x6E, 0x00, 0x69, 0x00, 0x66, 0x00, 0x79, 0x00, 0x69, 0x00,
    0x6E, 0x00, 0x67, 0x00, 0x20, 0x00, 0x52, 0x00, 0x61, 0x00, 0x64, 0x00, 0x69, 0x00,
    0x6F, 0x00, 0x20, 0x00, 0x54, 0x00, 0x58, 0x00 /* "Unifying Radio TX" */
};
const uint8_t string_product_len = sizeof(string_product);

/* app_tx has no extra descriptors (HID etc.) to handle. */
uint8_t usb_app_get_descriptor(uint8_t wValueH, uint8_t wLengthL, uint8_t wLengthH)
{
    (void)wValueH;
    (void)wLengthL;
    (void)wLengthH;
    return 0;
}

#define SEND_TEST_PACKET 0x10
#define GET_RADIO_DEBUG 0x12
#define SEND_KEY 0x13

#define KEY_EVENT_TYPE 0x01

static uint8_t seq;
static uint8_t last_send_ok;

void usb_vendor_request(uint8_t bRequest, uint8_t wValueL, uint8_t wValueH,
                         uint8_t wIndexL, uint8_t wIndexH,
                         uint8_t wLengthL, uint8_t wLengthH)
{
    (void)wIndexL;
    (void)wIndexH;
    (void)wLengthL;
    (void)wLengthH;

    if (bRequest == SEND_TEST_PACKET) {
        uint8_t pkt[RADIO_PKT_LEN];
        uint8_t s = seq++;
        /* pattern derived from s, different on every send, so the host
         * can independently recompute the expected value for each byte
         * and each send - distinguishes a position-dependent bug from a
         * value-dependent one. */
        pkt[0] = s;
        pkt[1] = s ^ 0xFF;
        pkt[2] = (uint8_t)(s * 3);
        pkt[3] = s ^ 0x5A;
        pkt[4] = (uint8_t)(s + 0x55);
        usb_ep0_ack();
        last_send_ok = radio_send(pkt);
        return;
    }

    if (bRequest == SEND_KEY) {
        /* wValueH = modifier, wValueL = keycode (HID usage), 1 OUT data
         * byte = down(1)/up(0). Same packet format as SEND_TEST_PACKET
         * but with the real KEY_EVENT type - see app_rx/main.c. */
        uint8_t pkt[RADIO_PKT_LEN];
        uint8_t downup;
        uint8_t s = seq++;

        usb_ep0_recv(&downup, 1);

        pkt[0] = KEY_EVENT_TYPE;
        pkt[1] = wValueH; /* modifier */
        pkt[2] = wValueL; /* keycode */
        pkt[3] = downup;
        pkt[4] = s;
        last_send_ok = radio_send(pkt);
        return;
    }

    if (bRequest == GET_RADIO_DEBUG) {
        uint8_t dbg[6];
        radio_debug_status(dbg);
        dbg[4] = last_send_ok;
        dbg[5] = radio_last_send_rounds();
        usb_ep0_send(dbg, 6);
        return;
    }

    usb_ep0_stall();
}

void main(void)
{
    usb_core_init();
    radio_init(RADIO_ROLE_TX);
    while (1) {
        usb_core_poll();
    }
}
