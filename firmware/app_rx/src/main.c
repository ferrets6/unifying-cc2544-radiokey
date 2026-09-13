/* app_rx - real USB HID boot-protocol keyboard. Always listens on radio
 * (../app_common/radio.c); when a valid KEY_EVENT packet arrives, turns
 * it into an 8-byte HID report and sends it on EP1 IN
 * (../app_rx/usb_hid.c) - the host sees it as a real keypress. Enumerates
 * as VID:PID 0x1209:0x0030 (bootloader=0x0010, bootloader_updater=0x0020,
 * app_tx/app_rx=0x0030, TX/RX distinguished only by iProduct), HID
 * boot-keyboard interface (class 0x03/1/1).
 */
#include "../../app_common/usb_core.h"
#include "../../app_common/radio.h"
#include "usb_hid.h"

__code const uint8_t device_descriptor[18] = {
    18, 0x01,       /* bLength, bDescriptorType=DEVICE */
    0x10, 0x01,     /* bcdUSB 1.10 */
    0x00,           /* bDeviceClass = 0: defined at interface level (HID) */
    0x00, 0x00,     /* bDeviceSubClass, bDeviceProtocol */
    32,             /* bMaxPacketSize0 */
    0x09, 0x12,     /* idVendor = 0x1209 */
    0x30, 0x00,     /* idProduct = 0x0030 */
    0x00, 0x01,     /* bcdDevice 1.00 */
    1, 2, 0,        /* iManufacturer, iProduct, iSerialNumber */
    0x01            /* bNumConfigurations */
};

/* String descriptors - see usb_core.h. */
__code const uint8_t string_lang_descriptor[4] = { 0x04, 0x03, 0x09, 0x04 }; /* LANGID: English (US) */
__code const uint8_t string_manufacturer[] = {
    0x32, 0x03, 0x75, 0x00, 0x6E, 0x00, 0x69, 0x00, 0x66, 0x00, 0x79, 0x00, 0x69, 0x00,
    0x6E, 0x00, 0x67, 0x00, 0x2D, 0x00, 0x63, 0x00, 0x63, 0x00, 0x32, 0x00, 0x35, 0x00,
    0x34, 0x00, 0x34, 0x00, 0x2D, 0x00, 0x72, 0x00, 0x61, 0x00, 0x64, 0x00, 0x69, 0x00,
    0x6F, 0x00, 0x6B, 0x00, 0x65, 0x00, 0x79, 0x00 /* "unifying-cc2544-radiokey" */
};
const uint8_t string_manufacturer_len = sizeof(string_manufacturer);
__code const uint8_t string_product[] = {
    0x36, 0x03, 0x55, 0x00, 0x6E, 0x00, 0x69, 0x00, 0x66, 0x00, 0x79, 0x00, 0x69, 0x00,
    0x6E, 0x00, 0x67, 0x00, 0x20, 0x00, 0x52, 0x00, 0x61, 0x00, 0x64, 0x00, 0x69, 0x00,
    0x6F, 0x00, 0x20, 0x00, 0x52, 0x00, 0x58, 0x00, 0x20, 0x00, 0x4B, 0x00, 0x65, 0x00,
    0x79, 0x00, 0x62, 0x00, 0x6F, 0x00, 0x61, 0x00, 0x72, 0x00, 0x64, 0x00 /* "Unifying Radio RX Keyboard" */
};
const uint8_t string_product_len = sizeof(string_product);

#define HID_REPORT_DESC_LEN 45

__code const uint8_t hid_report_descriptor[HID_REPORT_DESC_LEN] = {
    0x05, 0x01,       /* Usage Page (Generic Desktop) */
    0x09, 0x06,       /* Usage (Keyboard) */
    0xA1, 0x01,       /* Collection (Application) */
    0x05, 0x07,       /*   Usage Page (Key Codes) */
    0x19, 0xE0,       /*   Usage Minimum (224) */
    0x29, 0xE7,       /*   Usage Maximum (231) */
    0x15, 0x00,       /*   Logical Minimum (0) */
    0x25, 0x01,       /*   Logical Maximum (1) */
    0x75, 0x01,       /*   Report Size (1) */
    0x95, 0x08,       /*   Report Count (8) */
    0x81, 0x02,       /*   Input (Data,Var,Abs) - modifier byte */
    0x95, 0x01,       /*   Report Count (1) */
    0x75, 0x08,       /*   Report Size (8) */
    0x81, 0x01,       /*   Input (Const) - reserved byte */
    0x95, 0x06,       /*   Report Count (6) */
    0x75, 0x08,       /*   Report Size (8) */
    0x15, 0x00,       /*   Logical Minimum (0) */
    0x25, 0x65,       /*   Logical Maximum (101) */
    0x05, 0x07,       /*   Usage Page (Key Codes) */
    0x19, 0x00,       /*   Usage Minimum (0) */
    0x29, 0x65,       /*   Usage Maximum (101) */
    0x81, 0x00,       /*   Input (Data,Array) - 6 keycodes */
    0xC0              /* End Collection */
};

/* Configuration(9) + Interface(9, HID boot-keyboard) + HID(9) + Endpoint(7)
 * = 34 bytes total (wTotalLength below). */
__code const uint8_t config_descriptor[34] = {
    9, 0x02, 34, 0, 1, 1, 0, 0x80, 50,             /* CONFIGURATION */
    9, 0x04, 0, 0, 1, 0x03, 0x01, 0x01, 0,         /* INTERFACE: HID, Boot, Keyboard, 1 endpoint */
    9, 0x21, 0x11, 0x01, 0x00, 0x01, 0x22, HID_REPORT_DESC_LEN, 0x00, /* HID descriptor */
    7, 0x05, 0x81, 0x03, 8, 0, 10                  /* ENDPOINT: EP1 IN, Interrupt, 8 bytes, 10ms */
};
const uint8_t config_descriptor_len = 34;

uint8_t usb_app_get_descriptor(uint8_t wValueH, uint8_t wLengthL, uint8_t wLengthH)
{
    uint8_t len;

    if (wValueH == 0x21) { /* standalone HID descriptor (9 bytes, same as inside config_descriptor) */
        len = 9;
        if (wLengthH == 0 && wLengthL < len) {
            len = wLengthL;
        }
        usb_ep0_send(&config_descriptor[9 + 9], len);
        return 1;
    }
    if (wValueH == 0x22) { /* Report descriptor */
        len = HID_REPORT_DESC_LEN;
        if (wLengthH == 0 && wLengthL < len) {
            len = wLengthL;
        }
        usb_ep0_send(hid_report_descriptor, len);
        return 1;
    }
    return 0;
}

#define GET_LAST_PACKET 0x11
#define GET_RADIO_DEBUG 0x12

#define KEY_EVENT_TYPE 0x01

static uint8_t last_pkt[RADIO_PKT_LEN];
static uint8_t have_pkt;

void usb_vendor_request(uint8_t bRequest, uint8_t wValueL, uint8_t wValueH,
                         uint8_t wIndexL, uint8_t wIndexH,
                         uint8_t wLengthL, uint8_t wLengthH)
{
    (void)wValueL;
    (void)wValueH;
    (void)wIndexL;
    (void)wIndexH;
    (void)wLengthH;

    if (bRequest == GET_LAST_PACKET) {
        uint8_t resp[1 + RADIO_PKT_LEN];
        uint8_t n, i;

        resp[0] = have_pkt;
        for (i = 0; i < RADIO_PKT_LEN; i++) {
            resp[1 + i] = last_pkt[i];
        }

        n = wLengthL;
        if (n > sizeof(resp)) {
            n = sizeof(resp);
        }
        if (n > 0) {
            usb_ep0_send(resp, n);
        } else {
            usb_ep0_ack();
        }
        have_pkt = 0;
        return;
    }

    if (bRequest == GET_RADIO_DEBUG) {
        uint8_t dbg[5];
        radio_debug_status(dbg);
        usb_ep0_send(dbg, 5);
        return;
    }

    usb_ep0_stall();
}

void main(void)
{
    uint8_t buf[RADIO_PKT_LEN];

    usb_core_init();
    hid_init();
    radio_init(RADIO_ROLE_RX);

    while (1) {
        usb_core_poll();
        hid_poll();
        if (radio_recv_poll(buf, RADIO_PKT_LEN)) {
            uint8_t i;
            for (i = 0; i < RADIO_PKT_LEN; i++) {
                last_pkt[i] = buf[i];
            }
            have_pkt = 1;

            if (buf[0] == KEY_EVENT_TYPE) {
                if (buf[3] != 0) {
                    hid_send_report(buf[1], buf[2]); /* key down: modifier, keycode */
                } else {
                    hid_send_report(0, 0); /* key up */
                }
            }
        }
    }
}
