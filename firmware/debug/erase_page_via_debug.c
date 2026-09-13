/* Erases one arbitrary flash page (1024 bytes, FADDRH=page number - same
 * unit as the bootloader's USB ERASE_PAGE protocol, see
 * firmware/tools/flash_firmware.py PAGE_SIZE=1024) via debug -
 * generalization of erase_bootloader_page_via_debug.c (fixed to page 0)
 * to erase only app-area pages (>=1) without ever touching page 0 (the
 * bootloader). Requires -p <page> explicitly, no default, so page 0 is
 * never erased by accident.
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

int main(int argc, char *argv[])
{
    int opt;
    int rePin = 24, dcPin = 27, ddPin = 28;
    int page = -1;
    while ((opt = getopt(argc, argv, "d:c:r:p:")) != -1) {
        switch (opt) {
        case 'd': ddPin = atoi(optarg); break;
        case 'c': dcPin = atoi(optarg); break;
        case 'r': rePin = atoi(optarg); break;
        case 'p': page = atoi(optarg); break;
        }
    }
    if (page < 1) {
        fprintf(stderr, "usage: erase_page_via_debug -p <page, >=1> [-d ddPin] [-c dcPin] [-r rePin]\n");
        fprintf(stderr, "(page 0 is the bootloader - use erase_bootloader_page_via_debug.c for that)\n");
        return 1;
    }

    cc_init(rePin, dcPin, ddPin);
    cc_enter();
    fprintf(stderr, "  ID = %04x\n", cc_getChipID());

    uint8_t p = (uint8_t)page;
    writeXDATA(0x6272, &p, 1); /* FADDRH = page */
    { uint8_t erasecmd = 0x01; writeXDATA(0x6270, &erasecmd, 1); } /* FCTL.ERASE=1 */

    uint8_t fctl;
    int tries = 0;
    do {
        cc_execi(0x90, 0x6270);
        fctl = cc_exec(0xE0);
        tries++;
        usleep(2000);
    } while ((fctl & 0x80) && tries < 100);

    fprintf(stderr, "  page %d erase done after %d checks (FCTL=0x%02x)\n", page, tries, fctl);
    if (fctl & 0x80) {
        fprintf(stderr, "  ERROR: FCTL.BUSY still high\n");
        cc_setActive(false);
        return 1;
    }
    if (fctl & 0x20) {
        fprintf(stderr, "  ERROR: FCTL.ABORT high - page locked?\n");
        cc_setActive(false);
        return 1;
    }

    /* verify: read the page back, should be 0xFF everywhere (disable
     * the flash cache first, same note as write_bootloader_via_debug.c) */
    {
        uint8_t v;
        cc_execi(0x90, 0x6270);
        v = cc_exec(0xE0);
        cc_exec(0xA3);
        v &= ~0x0C;
        writeXDATA(0x6270, &v, 1);
    }
    int diffs = 0;
    uint8_t first_bad = 0;
    int first_bad_addr = -1;
    uint32_t base = 0x8000 + (uint32_t)page * 1024;
    cc_execi(0x90, base & 0xFFFF);
    for (int i = 0; i < 1024; i++) {
        uint8_t b = cc_exec(0xE0);
        cc_exec(0xA3);
        if (b != 0xFF) {
            diffs++;
            if (first_bad_addr < 0) { first_bad_addr = i; first_bad = b; }
        }
    }
    fprintf(stderr, "  verify: %d bytes differ from 0xFF out of 1024", diffs);
    if (diffs) fprintf(stderr, " (first at offset 0x%04x = 0x%02x)", first_bad_addr, first_bad);
    fprintf(stderr, "\n");

    cc_setActive(false);
    return diffs ? 1 : 0;
}
