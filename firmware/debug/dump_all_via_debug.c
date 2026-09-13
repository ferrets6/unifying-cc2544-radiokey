/* READ-ONLY: dumps ID/status, the XREG area (0x6000-0x63FF), the
 * factory info page (XDATA 0x7800-0x7FFF, SWRU283B: "read-only area,
 * contains various information about the device"), and the full flash
 * (32KB, XDATA 0x8000-0xFFFF with XMAP=0) - used to compare two
 * different chips and isolate clock/trim/factory config differences
 * from the obvious content differences (bootloader/app). Never writes.
 *
 * Usage: dump_all_via_debug -r <rst> -c <dc> -d <dd> <output_prefix>
 */
#include <wiringPi.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdint.h>
#include <unistd.h>
#include <string.h>

#include "CCDebugger.h"

static void readXDATA(uint16_t offset, uint8_t *bytes, uint32_t len)
{
    cc_execi(0x90, offset);
    for (uint32_t i = 0; i < len; i++) {
        bytes[i] = cc_exec(0xE0);
        cc_exec(0xA3);
    }
}

static void dump_region(const char *prefix, const char *name, uint32_t xdata_addr, uint32_t len)
{
    char path[256];
    snprintf(path, sizeof(path), "%s_%s.bin", prefix, name);
    uint8_t *buf = malloc(len);
    readXDATA((uint16_t)(xdata_addr & 0xFFFF), buf, len);
    FILE *f = fopen(path, "wb");
    fwrite(buf, 1, len, f);
    fclose(f);
    fprintf(stderr, "  %s: %u bytes -> %s\n", name, len, path);
    free(buf);
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
    if (optind >= argc) {
        fprintf(stderr, "usage: %s [-r rst][-c dc][-d dd] <output_prefix>\n", argv[0]);
        exit(1);
    }
    const char *prefix = argv[optind];

    cc_init(rePin, dcPin, ddPin);
    cc_enter();

    uint16_t chipid = cc_getChipID();
    uint8_t status = cc_getStatus();
    fprintf(stderr, "  ID = %04x, debug status = %02x (right after cc_enter, before anything else)\n", chipid, status);

    {
        char path[256];
        snprintf(path, sizeof(path), "%s_id_status.txt", prefix);
        FILE *f = fopen(path, "w");
        fprintf(f, "chipid=%04x status=%02x\n", chipid, status);
        fclose(f);
    }

    dump_region(prefix, "xreg_6000_63FF", 0x6000, 0x0400);       /* FCTL, radio, USB, all XREG */
    dump_region(prefix, "sfrmirror_7000_70FF", 0x7000, 0x0100);   /* SFR mirror incl. CLKCONSTA/MEMCTR */
    dump_region(prefix, "infopage_7800_7FFF", 0x7800, 0x0800);   /* factory info page, 2KB */
    dump_region(prefix, "flash_8000_FFFF", 0x8000, 0x8000);       /* full flash, 32KB */

    cc_setActive(false);
    return 0;
}
