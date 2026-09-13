/***********************************************************************
  Copyright © 2019 Jean Michault.
    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.
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
  fprintf(stderr,"usage : erase_chip_via_debug [-d pin_DD] [-c pin_DC] [-r pin_reset]\n");
  fprintf(stderr,"  WARNING: erases the ENTIRE chip (not just the bootloader).\n");
  fprintf(stderr,"	-c : change pin_DC (default 27)\n");
  fprintf(stderr,"	-d : change pin_DD (default 28)\n");
  fprintf(stderr,"	-r : change reset pin (default 24)\n");
  fprintf(stderr,"	-m : change multiplier for time delay (default auto)\n");
}

int main(int argc,char *argv[])
{
  int opt;
  int rePin=-1;
  int dcPin=-1;
  int ddPin=-1;
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
  // enter debug mode
  cc_enter();
  // get ChipID :
  uint16_t res;
  res = cc_getChipID();
  printf("  ID = %04x.\n",res);
  // erase flash - CHIP_ERASE goes busy (bit 7 = CHIP_ERASE_BUSY) right
  // away and stays busy until the whole chip is actually erased -
  // reading status once right after the command almost always still
  // shows busy=1, not the final outcome. Without waiting, a subsequent
  // write could start while the erase is still in progress.
  res = cc_chipErase();
  printf("  erase result (right after the command, almost certainly BUSY) = %04x.\n",res);
  {
    int tries = 0;
    uint8_t st;
    do {
      usleep(50000);
      st = cc_getStatus();
      tries++;
    } while ((st & 0x80) && tries < 200); // up to 10s margin
    if (st & 0x80) {
      fprintf(stderr, "  ERROR: CHIP_ERASE_BUSY still high after %d tries (status=0x%02x) - erase not completed\n", tries, st);
      exit(1);
    }
    printf("  erase done after %d checks (final status = 0x%02x)\n", tries, st);
  }
  cc_setActive(false);

}
