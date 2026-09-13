/***********************************************************************
  Read-only tool: reads CHIPID/CHVER via the debug interface, never
  erases or writes flash. Exits debug mode with a clean cc_exit(),
  resuming the chip exactly as a normal hardware reset would.

  Usage: sudo ./get_chip_id [-r pin_reset] [-c pin_DC] [-d pin_DD] [-m mult]
  With no arguments, uses the standard pins (24/27/28, CCDebugger.h) -
  pass -r/-c/-d only if the wiring differs.

  The high byte of cc_getChipID()'s return value is CHIPID (XREG
  0x624A): 0x43=CC2543, 0x44=CC2544, 0x45=CC2545. The low byte is CHVER
  (silicon revision).
*************************************************************************/

#include <wiringPi.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdbool.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>

#include "CCDebugger.h"

void helpo()
{
  fprintf(stderr,"usage : get_chip_id [-d pin_DD] [-c pin_DC] [-r pin_reset] [-m mult]\n");
  fprintf(stderr,"  Read-only: reads CHIPID/CHVER via the debug interface, no erase/write.\n");
  fprintf(stderr,"  With no arguments, uses the standard pins (24/27/28, CCDebugger.h).\n");
  fprintf(stderr,"	-c : override pin_DC\n");
  fprintf(stderr,"	-d : override pin_DD\n");
  fprintf(stderr,"	-r : override reset pin\n");
  fprintf(stderr,"	-m : change multiplier for time delay (default auto)\n");
}

int main(int argc,char *argv[])
{
  int opt;
  int rePin=PIN_RST;
  int dcPin=PIN_DC;
  int ddPin=PIN_DD;
  int setMult=-1;

  while( (opt=getopt(argc,argv,"m:d:c:r:h?")) != -1)
  {
    switch(opt)
    {
     case 'm' :
      setMult=atoi(optarg);
      break;
     case 'd' :
      ddPin=atoi(optarg);
      break;
     case 'c' :
      dcPin=atoi(optarg);
      break;
     case 'r' :
      rePin=atoi(optarg);
      break;
     case 'h' :
     case '?' :
      helpo();
      exit(0);
      break;
    }
  }

  // initialize GPIO and debugger
  cc_init(rePin,dcPin,ddPin);
  if(setMult>0) cc_setmult(setMult);

  // enter debug mode (halts CPU at reset vector, does NOT touch flash)
  cc_enter();

  uint16_t res;
  res = cc_getChipID();
  uint8_t chipid = (res >> 8) & 0xFF;
  uint8_t chver  = res & 0xFF;

  printf("  raw GET_CHIP_ID = %04x\n", res);
  printf("  CHIPID = 0x%02x -> %s\n", chipid,
         chipid == 0x43 ? "CC2543" :
         chipid == 0x44 ? "CC2544" :
         chipid == 0x45 ? "CC2545" : "unknown/not CC254x");
  printf("  CHVER  = 0x%02x (silicon revision)\n", chver);

  uint8_t status = cc_getStatus();
  printf("  debug status = 0x%02x\n", status);

  // exit debug mode with no erase/write: RESUME returns the chip to
  // normal execution (bootloader -> app), like a clean reset.
  cc_exit();
  cc_setActive(false);

  return 0;
}
