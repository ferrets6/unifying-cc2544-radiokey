/* Reset-only tool via the debug interface: enters debug mode (halts the
 * CPU at the reset vector, doesn't touch flash) and exits right away -
 * equivalent to a clean external reset via RESET_N, used to restart the
 * chip from page 0 when a USB SOFT_RESET isn't available (e.g. while
 * bootloader_updater is active, which doesn't implement that command).
 *
 * Usage: sudo ./cc_reset_only [-r pin_reset] [-c pin_DC] [-d pin_DD]
 * With no arguments, uses the standard pins (24/27/28, CCDebugger.h).
 */
#include <wiringPi.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>

#include "CCDebugger.h"

int main(int argc, char *argv[])
{
    int opt;
    int rePin = PIN_RST, dcPin = PIN_DC, ddPin = PIN_DD;

    while ((opt = getopt(argc, argv, "d:c:r:h?")) != -1) {
        switch (opt) {
        case 'd': ddPin = atoi(optarg); break;
        case 'c': dcPin = atoi(optarg); break;
        case 'r': rePin = atoi(optarg); break;
        case 'h': case '?':
            fprintf(stderr, "usage: %s [-r pin_reset] [-c pin_DC] [-d pin_DD]\n", argv[0]);
            exit(0);
        }
    }

    cc_init(rePin, dcPin, ddPin);
    cc_enter();
    cc_exit();
    cc_setActive(false);

    return 0;
}
