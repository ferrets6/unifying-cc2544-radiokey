/***********************************************************************
  Copyright © 2019 Jean Michault.
    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

  Adapted for TI CC2544 - "CPU MODE" variant.
  ============================================================
  Writes the APP AREA (addresses >= 0x0400) to flash via the debug
  interface (DC/DD/RESET), using the "CPU Flash Write" method from the
  TI SWRU283B User's Guide (6.2.1/6.2.4) - not the DMA method (damaged
  on this project's dev dongle, chip ID 4414).

  Refuses to write any byte below 0x0400 (page 0, the bootloader) - use
  write_bootloader_via_debug for the bootloader itself, which has the
  opposite restriction (page 0 only, never the app area). Doesn't erase
  the target pages itself - erase first with erase_page_via_debug; the
  write only checks they are already 0xFF where needed.

  Asks whether to start the app right after writing: a reset from debug
  (external RESET_N) always makes the bootloader read SLEEPSTA.RST=01,
  never 00 (power-on), so it would always stay listening in the
  bootloader - a debug "reboot" that lands in the app doesn't exist.
  Actually starting the app means jumping straight to 0x0400 by
  injecting the instruction via debug (same idea as the USB APP_RESTART
  command, but without ever going through the bootloader).

  USE THIS TOOL (CPU method) by default on any chip, healthy or not -
  it's the one actually validated in this project. The DMA method was
  never ported/tested here.

  Typical use (bootstrapping a new dongle that already has the
  bootloader, writing the firmware/app via debug instead of USB):
    ./erase_page_via_debug -p 1 [-p 2 ...]   # erase ONLY the app pages involved
    ./write_app_via_debug ../app_tx/bin/app_tx.ihx
*************************************************************************/

#include <wiringPi.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdbool.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>

#include "CCDebugger.h"

int vorte=0;

uint8_t buffer[601];
uint8_t data[260];
uint8_t verif1[2048];
uint8_t verif2[2048];

struct page
{
  uint32_t minoffset,maxoffset;
  uint8_t datas[2048];
} Pages[16]; // CC2544: 16 pages x 2KB = 32KB total

void writeXDATA(uint16_t offset,uint8_t *bytes, int len)
{
  cc_execi(0x90, offset ); //MOV DPTR,#data16
  for ( int i=0 ; i<len;i++)
  {
    cc_exec2(0x74,bytes[i]); // MOV A,#data
    cc_exec(0xF0);	//MOVX @DPTR,A
    cc_exec(0xA3);	// INC DPTR
  }
}

void readXDATA(uint16_t offset,uint8_t *bytes, int len)
{
  cc_execi(0x90, offset );
  for ( int i=0 ; i<len;i++)
  {
    bytes[i] = cc_exec(0xE0);
    cc_exec(0xA3);
  }
}

void readPage(int page,uint8_t *buf)
{
  {
    uint8_t fctl;
    readXDATA(0x6270, &fctl, 1);
    fctl &= ~0x0C; // disable the flash cache (freshly written data)
    writeXDATA(0x6270, &fctl, 1);
  }
  uint32_t offset = (page<<11) + Pages[page].minoffset;
  cc_execi( 0x90, 0x8000+offset );
  for(int i=Pages[page].minoffset ; i<=Pages[page].maxoffset ;i++)
  {
    uint8_t res = cc_exec  ( 0xE0 );
    buf[i] = res;
    res = cc_exec  ( 0xA3 );
  }
}

int verifPage(int page)
{
  int nerr = 0;
  for(int i=Pages[page].minoffset ; i<=Pages[page].maxoffset ;i++)
  {
    if(verif1[i] != Pages[page].datas[i])
    {
      if(vorte && nerr < 40) fprintf(stderr,"\nerror at 0x%x, 0x%x instead of 0x%x\n",i,verif1[i],Pages[page].datas[i]);
      nerr++;
    }
  }
  if (nerr && vorte) fprintf(stderr, "\ntotal differing bytes: %d out of %d\n", nerr, Pages[page].maxoffset - Pages[page].minoffset + 1);
  return nerr != 0;
}

/* --- CPU method (no DMA) --- */

/* Compiled payload of ram_flash_write.c: routine that runs from RAM and
 * writes 4-byte words to flash, reading parameters from XDATA 0x0200+
 * (FADDRH,FADDRL,nwords) and data from XDATA 0x0210+. Loaded at 0x8000
 * in CODE space (i.e. XDATA 0x0000 with MEMCTR.XMAP=1). */
static const uint8_t ram_routine[] = {
0x02,0x80,0x4c,0xff,0xff,0xff,0xff,0xff,0x00,0x00,0xe2,0xfb,0xea,0xf2,0x80,0x2c,0x00,0x00,0xe0,0xfb,0xea,0xf0,0x80,0x24,0xe6,0xb5,0x02,0x02,0xeb,0xf6,0x22,0x00,0xe2,0xb5,0x02,0x02,0xeb,0xf2,0x22,0x00,0xe0,0xb5,0x02,0x02,0xeb,0xf0,0x22,0x30,0xf6,0xe0,0xa8,0x82,0x20,0xf5,0xd3,0xea,0xc6,0xf5,0x82,0x22,0x8b,0x82,0x22,0x30,0xf6,0xe6,0xa8,0x82,0x20,0xf5,0xd9,0x80,0xcf,0x02,0x80,0xa8,0x75,0x81,0x07,0x12,0x81,0x43,0xe5,0x82,0x60,0x03,0x02,0x80,0x49,0x79,0x00,0xe9,0x44,0x00,0x60,0x1b,0x7a,0x00,0x90,0x81,0x47,0x78,0x00,0x75,0xa0,0x00,0xe4,0x93,0xf2,0xa3,0x08,0xb8,0x00,0x02,0x05,0xa0,0xd9,0xf4,0xda,0xf2,0x75,0xa0,0xff,0xe4,0x78,0xff,0xf6,0xd8,0xfd,0x78,0x00,0xe8,0x44,0x00,0x60,0x0a,0x79,0x00,0x75,0xa0,0x00,0xe4,0xf3,0x09,0xd8,0xfc,0x78,0x00,0xe8,0x44,0x00,0x60,0x0c,0x79,0x00,0x90,0x00,0x00,0xe4,0xf0,0xa3,0xd8,0xfc,0xd9,0xfa,0x02,0x80,0x49,0x90,0x01,0x40,0x74,0xaa,0xf0,0x90,0x02,0x00,0xe0,0x90,0x62,0x72,0xf0,0x90,0x02,0x01,0xe0,0x90,0x62,0x71,0xf0,0x90,0x02,0x02,0xe0,0xfe,0x7f,0x00,0xa3,0xe0,0x7c,0x00,0x42,0x07,0xec,0x42,0x06,0x90,0x01,0x40,0x74,0xa1,0xf0,0x90,0x62,0x70,0x74,0x02,0xf0,0x7c,0x00,0x7d,0x00,0xc3,0xec,0x9f,0xed,0x9e,0x50,0x50,0x8c,0x02,0x8d,0x03,0xea,0x2a,0xfa,0xeb,0x33,0xfb,0xea,0x2a,0xfa,0xeb,0x33,0xfb,0x74,0x10,0x2a,0xfa,0x74,0x02,0x3b,0xfb,0x8a,0x82,0x8b,0x83,0xe0,0x90,0x62,0x73,0xf0,0x8a,0x82,0x8b,0x83,0xa3,0xe0,0x90,0x62,0x73,0xf0,0x8a,0x82,0x8b,0x83,0xa3,0xa3,0xe0,0x90,0x62,0x73,0xf0,0x8a,0x82,0x8b,0x83,0xa3,0xa3,0xa3,0xe0,0x90,0x62,0x73,0xf0,0x90,0x62,0x70,0xe0,0x20,0xe6,0xf9,0x0c,0xbc,0x00,0xac,0x0d,0x80,0xa9,0x90,0x01,0x40,0x74,0xbb,0xf0,0x90,0x01,0x40,0x74,0xcc,0xf0,0x80,0xf8,0x75,0x82,0x00,0x22
};
#define RAM_ROUTINE_LEN (sizeof(ram_routine))

#define P_FADDRH   0x0200
#define P_FADDRL   0x0201
#define P_NWORDS   0x0202
#define P_DATA     0x0210
#define MAX_CHUNK_WORDS 300 /* 1200 data bytes, well within the 2KB SRAM with routine+params */

static int ram_routine_loaded = 0;

void load_ram_routine(void)
{
  writeXDATA(0x0000, (uint8_t*)ram_routine, RAM_ROUTINE_LEN);
  ram_routine_loaded = 1;
}

/* Writes nwords 4-byte words (already aligned) starting at byte address
 * byteaddr, using the CPU method (no DMA). */
void cpuWriteWords(uint32_t byteaddr, const uint8_t *databytes, int nwords)
{
  if (!ram_routine_loaded) load_ram_routine();

  uint32_t wordaddr = byteaddr >> 2;
  uint8_t faddrh = (wordaddr >> 8) & 0xff;
  uint8_t faddrl = wordaddr & 0xff;
  uint8_t nh = (nwords >> 8) & 0xff;
  uint8_t nl = nwords & 0xff;

  writeXDATA(P_FADDRH, &faddrh, 1);
  writeXDATA(P_FADDRL, &faddrl, 1);
  {
    uint8_t nw[2] = { nh, nl };
    writeXDATA(P_NWORDS, nw, 2);
  }
  writeXDATA(P_DATA, (uint8_t*)databytes, nwords*4);

  // enable execution from RAM
  { uint8_t v = 0x08; writeXDATA(0x70C7, &v, 1); }

  // LJMP 0x8000 injected via the debug interface, then RESUME at full speed
  cc_exec3(0x02, 0x80, 0x00);
  cc_resume();

  // wait time: 20us/word nominal, wide margin
  usleep(2000 + nwords*50);

  cc_halt();

  // disable XMAP right away, otherwise 0x8000+ still shows RAM
  { uint8_t v = 0x00; writeXDATA(0x70C7, &v, 1); }
}

void writePage(int page)
{
  Pages[page].minoffset = (Pages[page].minoffset & 0xfffffffc);
  Pages[page].maxoffset = (Pages[page].maxoffset |0x3);
  uint32_t offset = (page<<11) + Pages[page].minoffset;
  uint32_t total_len = Pages[page].maxoffset-Pages[page].minoffset+1;

  uint32_t done = 0;
  while (done < total_len) {
    uint32_t len = total_len - done;
    uint32_t maxbytes = MAX_CHUNK_WORDS*4;
    if (len > maxbytes) len = maxbytes;
    // round down to a multiple of 4, the remainder goes in the next round
    len &= ~0x3;
    if (len == 0) len = 4; // edge case: last piece < 4 bytes, still one word

    cpuWriteWords(offset+done, &Pages[page].datas[Pages[page].minoffset+done], len/4);

    done += len;
    printf(".");
    fflush(stdout);
  }

  // final check: no leftover ABORT/BUSY
  uint8_t fctl;
  readXDATA(0x6270, &fctl, 1);
  fprintf(stderr, "\n FCTL after writing page %d = 0x%02x (bit7=erase_busy bit6=write_busy bit5=abort)\n", page, fctl);
  if (fctl & 0x20)
  {
    fprintf(stderr,"\n flash abort on page %d (FCTL=0x%02x)\n", page, fctl);
    exit(1);
  }
}

void helpo()
{
  fprintf(stderr,"usage : write_app_via_debug [-d pin_DD] [-c pin_DC] [-r pin_reset] file_to_flash\n");
  fprintf(stderr,"  Refuses any byte below 0x0400 (page 0, bootloader).\n");
  fprintf(stderr,"  CPU method (not DMA) - see the comment at the top of the file for why.\n");
  fprintf(stderr,"	-c : change pin_DC (default 27)\n");
  fprintf(stderr,"	-d : change pin_DD (default 28)\n");
  fprintf(stderr,"	-r : change reset pin (default 24)\n");
  fprintf(stderr,"	-m : change multiplier for time delay (default auto)\n");
}

int main(int argc,char *argv[])
{
  int opt;
  int rePin=24;
  int dcPin=27;
  int ddPin=28;
  int setMult=-1;
  int readOnly=0;
  while( (opt=getopt(argc,argv,"Rvm:d:c:r:h?")) != -1)
  {
    switch(opt)
    {
     case 'm' : setMult=atoi(optarg); break;
     case 'd' : ddPin=atoi(optarg); break;
     case 'c' : dcPin=atoi(optarg); break;
     case 'r' : rePin=atoi(optarg); break;
     case 'v' : vorte++; break;
     case 'R' : readOnly=1; break;
     case 'h' : case '?' : helpo(); exit(0); break;
    }
  }
  if (readOnly) {
    /* diagnostic: read page 0 using readPage() exactly (same FCTL
     * handling via the real writeXDATA, not a reimplementation) and
     * print it - no write, no file needed. */
    cc_init(rePin,dcPin,ddPin);
    cc_enter();
    printf("  ID = %04x.\n", cc_getChipID());
    Pages[0].minoffset = 0;
    Pages[0].maxoffset = 63;
    uint8_t buf[64];
    readPage(0, buf);
    for (int i = 0; i < 64; i++) {
      printf("%02x%c", buf[i], ((i&15)==15) ? '\n' : ' ');
    }
    cc_setActive(false);
    return 0;
  }
  if( optind >= argc ) { helpo(); exit(1); }
  FILE * ficin = fopen(argv[optind],"r");
  if(!ficin) { fprintf(stderr," Can't open file %s.\n",argv[optind]); exit(1); }

  cc_init(rePin,dcPin,ddPin);
  if(setMult>0) cc_setmult(setMult);
  cc_enter();
  uint16_t ID;
  ID = cc_getChipID();
  printf("  ID = %04x.\n",ID);
  if (ID != 0x4414) {
    fprintf(stderr, "NOTE: chip ID different from 0x4414 (this project's original dev dongle) - normal on a different unit. This tool (CPU method) still works, just a bit slower than DMA.\n");
  }

  for (int page=0 ; page<16 ; page++)
  {
    memset(Pages[page].datas,0xff,2048);
    Pages[page].minoffset=0xffff;
    Pages[page].maxoffset=0;
  }

  uint16_t ela=0;
  uint32_t sla=0;
  int line=0;
  int maxpage=0;
  while(fgets((char*)buffer,600,ficin))
  {
    int sum=0,cksum,type;
    uint32_t addr,len;
    line++;
    if(line%10==0) { printf("\r  reading line %d.",line);fflush(stdout); }
    if(buffer[0] != ':') { fprintf(stderr,"incorrect hex file ( : missing)\n"); exit(1); }
    if(strlen((char*)buffer)<3 ) { fprintf(stderr,"incorrect hex file ( incomplete line)\n"); exit(1); }
    if(!sscanf((char*)buffer+1,"%02x",&len)) { fprintf(stderr,"incorrect hex file (incorrect length\n"); exit(1); }
    if(strlen((char*)buffer)<(11 + (len * 2))) { fprintf(stderr,"incorrect hex file ( incomplete line)\n"); exit(1); }
    if(!sscanf((char*)buffer+3,"%04x",&addr)) { fprintf(stderr,"incorrect hex file (incorrect addr)\n"); exit(1); }
    if(!sscanf((char*)buffer+7,"%02x",&type)) { fprintf(stderr,"incorrect hex file (incorrect record type\n"); exit(1); }
    if(type == 4)
    {
      if(!sscanf((char*)buffer+9,"%04hx",&ela)) { fprintf(stderr,"incorrect hex file (incorrect extended addr)\n"); exit(1); }
      sla=ela<<16;
      continue;
    }
    if(type == 5)
    {
      if(!sscanf((char*)buffer+9,"%08x",&sla)) { fprintf(stderr,"incorrect hex file (incorrect extended addr)\n"); exit(1); }
      ela = sla>>16;
      continue;
    }
    if(type==1) break;
    if(type) { fprintf(stderr,"incorrect hex file (record type %d not implemented\n",type); exit(1); }
    sum = (len & 255) + ((addr >> 8) & 255) + (addr & 255) + (type & 255);
    int i;
    for( i=0 ; i<(int)len ; i++)
    {
      if(!sscanf((char*)buffer+9+2*i,"%02hhx",&data[i])) { fprintf(stderr,"incorrect hex file (incorrect data)\n"); exit(1); }
      sum+=data[i];
    }
    if(!sscanf((char*)buffer+9+2*i,"%02x",&cksum)) { fprintf(stderr,"incorrect hex file line %d (incorrect checksum)\n",line); exit(1); }
    if ( ((sum & 255) + (cksum & 255)) & 255 ) { fprintf(stderr,"incorrect hex file line %d (bad checksum) %x %x\n",line,(-sum)&255,cksum); exit(1); }
    int page= (sla+addr)>>11;
    if (page>maxpage) maxpage=page;
    uint16_t start=(sla+addr)&0x7ff;
    if(start+len> 2048)
    {
      if (page+1>maxpage) maxpage=page+1;
      memcpy(&Pages[page+1].datas[0],data+2048-start,(start+len-2048));
      if(0 < Pages[page+1].minoffset) Pages[page+1].minoffset=0;
      if( (start+len-2048-1) > Pages[page].maxoffset) Pages[page].maxoffset=start+len-2048-1;
      len=2048-start;
    }
    memcpy(&Pages[page].datas[start],data,len);
    if(start < Pages[page].minoffset) Pages[page].minoffset=start;
    if( (start+len-1) > Pages[page].maxoffset) Pages[page].maxoffset=start+len-1;
  }
  printf("\n  file loaded (%d lines read).\n",line);

  if (Pages[0].minoffset <= Pages[0].maxoffset && Pages[0].minoffset < 0x0400) {
    fprintf(stderr, "SAFETY ERROR: the file contains bytes below 0x0400 (page 0, "
                     "the bootloader) - this tool writes ONLY the app area. Use "
                     "write_bootloader_via_debug for the bootloader.\n");
    exit(1);
  }

  // Switch to the 32MHz XOSC, same as the DMA variant.
  {
    uint8_t v = 0x80;
    writeXDATA(0x70C6, &v, 1);
    int i;
    for (i = 0; i < 30; i++) {
      usleep(50000);
      readXDATA(0x709E, &v, 1);
      if (v == 0x80) break;
    }
    fprintf(stderr, "  final CLKCONSTA = 0x%02x after %d tries (expected 0x80)\n", v, i);
  }

  int provo=0;
  for (int page=0 ; page <= maxpage ; page++)
  {
    provo++;
    if(Pages[page].maxoffset<Pages[page].minoffset) continue;
    printf("\rwriting page %3d/%3d.",page+1,maxpage+1);
    fflush(stdout);
    writePage(page);
    memset(verif1,0xff,2048);
    readPage(page,verif1);
    if(verifPage(page))
    {
      printf("!");
      memset(verif2,0xff,2048);
      readPage(page,verif2);
      if(memcmp(verif1,verif2,2048))
      {
        memcpy(verif1,verif2,2048);
        if(verifPage(page)) page--;
      }
      else
        page--;
      if(provo>10)
      {
        fprintf(stderr,"verification error... Have you erased before write ?\n");
        exit(1);
      }
    }
    else
      provo=0;
  }
  printf("\n");
  printf(" flash OK.\n");

  /* A reset from debug (external RESET_N, cc_reset() below) always
   * makes the bootloader read SLEEPSTA.RST=01, never 00 (power-on) - by
   * design the bootloader treats any non-power-on cause as "keep
   * listening" (see bootloader.asm). So a debug "reboot" that lands in
   * the app doesn't exist: either it stays listening in the bootloader,
   * or it jumps straight to 0x0400 by injecting the instruction via
   * debug (same idea as USB's APP_RESTART, but without ever going
   * through the bootloader). */
  fprintf(stderr, "\nStart the app now (direct jump to 0x0400 via debug, "
                  "no reset)? A debug reset never reaches the app - it "
                  "would stay listening in the bootloader. [y/N] ");
  {
    char answer[16] = {0};
    fgets(answer, sizeof(answer), stdin);
    if (answer[0] == 'y' || answer[0] == 'Y') {
      cc_exec3(0x02, 0x04, 0x00); /* LJMP 0x0400 */
      cc_resume();
      cc_setActive(false);
      printf("App started (no reset - SLEEPSTA.RST unchanged).\n");
    } else {
      cc_setActive(false);
      cc_reset();
      printf("Chip reset - the bootloader stays listening (external cause, not power-on).\n");
    }
  }
  fclose(ficin);
  return 0;
}
