/* Erases only page 0 (the bootloader, 0x0000-0x03FF) via debug - unlike
 * erase_chip_via_debug.c (CHIP_ERASE, the whole chip), this uses the
 * normal flash controller mechanism (FADDRH + FCTL.ERASE, SWRU283B
 * 6.3), the same path the bootloader itself uses to erase a page,
 * driven externally while the chip is halted.
 */
#include <wiringPi.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdint.h>
#include <unistd.h>

#include "CCDebugger.h"

void writeXDATA(uint16_t offset, uint8_t *bytes, int len)
{
    cc_execi(0x90, offset);
    for (int i = 0; i < len; i++) {
        cc_exec2(0x74, bytes[i]);
        cc_exec(0xF0);
        cc_exec(0xA3);
    }
}

void readXDATA(uint16_t offset, uint8_t *bytes, int len)
{
    cc_execi(0x90, offset);
    for (int i = 0; i < len; i++) {
        bytes[i] = cc_exec(0xE0);
        cc_exec(0xA3);
    }
}

int main(int argc, char *argv[])
{
    int opt;
    int rePin = 24, dcPin = 27, ddPin = 28;
    while ((opt = getopt(argc, argv, "d:c:r:")) != -1) {
        switch (opt) {
        case 'd': ddPin = atoi(optarg); break;
        case 'c': dcPin = atoi(optarg); break;
        case 'r': rePin = atoi(optarg); break;
        }
    }

    cc_init(rePin, dcPin, ddPin);
    cc_enter();
    fprintf(stderr, "  ID = %04x\n", cc_getChipID());

    uint8_t page = 0;
    writeXDATA(0x6272, &page, 1); /* FADDRH = 0 (page 0) */
    { uint8_t erasecmd = 0x01; writeXDATA(0x6270, &erasecmd, 1); } /* FCTL.ERASE=1 */

    uint8_t fctl;
    int tries = 0;
    do {
        readXDATA(0x6270, &fctl, 1);
        tries++;
        usleep(2000);
    } while ((fctl & 0x80) && tries < 100); /* ~20ms nominal, wide margin */

    fprintf(stderr, "  page 0 erase done after %d checks (FCTL=0x%02x)\n", tries, fctl);
    if (fctl & 0x80) {
        fprintf(stderr, "  ERROR: FCTL.BUSY still high - erase not completed\n");
        cc_setActive(false);
        return 1;
    }
    if (fctl & 0x20) {
        fprintf(stderr, "  ERROR: FCTL.ABORT high - page locked?\n");
        cc_setActive(false);
        return 1;
    }

    /* verify: read page 0 back, should be 0xFF everywhere */
    {
        uint8_t v;
        readXDATA(0x6270, &v, 1);
        v &= ~0x0C;
        writeXDATA(0x6270, &v, 1);
    }
    int diffs = 0;
    uint8_t first_bad = 0;
    int first_bad_addr = -1;
    cc_execi(0x90, 0x8000);
    for (int i = 0; i < 1024; i++) {
        uint8_t b = cc_exec(0xE0);
        cc_exec(0xA3);
        if (b != 0xFF) {
            diffs++;
            if (first_bad_addr < 0) { first_bad_addr = i; first_bad = b; }
        }
    }
    fprintf(stderr, "  verify: %d bytes differ from 0xFF out of 1024", diffs);
    if (diffs) fprintf(stderr, " (first at 0x%04x = 0x%02x)", first_bad_addr, first_bad);
    fprintf(stderr, "\n");

    cc_setActive(false);
    return diffs ? 1 : 0;
}
