/* DMA variant (TI's "preferred method") of the RAM-resident flash-write
 * routine, for a healthy chip - this project's dev dongle has damaged
 * write DMA, so the bootloader uses the CPU method instead (see
 * firmware/debug/README.md). Untested on real hardware here (no healthy
 * chip available) - kept for completeness and for anyone continuing
 * this work with a chip that doesn't have this specific fault.
 *
 * `do_flash_write` is a function with a real RET, called via native
 * LCALL at the address read from the .map file - `main()` exists only
 * to satisfy SDCC, never actually runs.
 *
 * Same parameter layout as the CPU variant, so the bootloader code that
 * calls it is identical either way:
 *   0x0200-0x0201: FADDRH, FADDRL
 *   0x0202-0x0203: number of 4-byte WORDS (big-endian)
 *   0x0210+      : data to write, word_count*4 bytes
 *
 * DMA descriptor in RAM at 0x0400 (not 0x0200, to avoid overlapping the
 * parameters above) - 8 bytes, well within the 2KB SRAM.
 */
#include <stdint.h>

#define FCTL    (*(volatile __xdata uint8_t *)0x6270)
#define FADDRL  (*(volatile __xdata uint8_t *)0x6271)
#define FADDRH  (*(volatile __xdata uint8_t *)0x6272)

#define DMA1CFGL (*(volatile __xdata uint8_t *)0x70D2)
#define DMA1CFGH (*(volatile __xdata uint8_t *)0x70D3)
#define DMAIRQ   (*(volatile __xdata uint8_t *)0x70D1)
#define DMAARM   (*(volatile __xdata uint8_t *)0x70D6)

#define P_FADDRH   (*(volatile __xdata uint8_t *)0x0200)
#define P_FADDRL   (*(volatile __xdata uint8_t *)0x0201)
#define P_NWORDS_HI (*(volatile __xdata uint8_t *)0x0202)
#define P_NWORDS_LO (*(volatile __xdata uint8_t *)0x0203)

#define DMA_DESC ((__xdata uint8_t *)0x0400)

void do_flash_write(void)
{
  uint16_t nwords;
  uint16_t nbytes;
  uint8_t i;

  FADDRH = P_FADDRH;
  FADDRL = P_FADDRL;
  nwords = ((uint16_t)P_NWORDS_HI << 8) | P_NWORDS_LO;
  nbytes = nwords * 4;

  FCTL &= 0x1F; /* pulisci stato flash residuo (BUSY/FULL/ABORT) */

  DMA_DESC[0] = 0x02; /* src[15:8] (0x0210 >> 8) */
  DMA_DESC[1] = 0x10; /* src[7:0] */
  DMA_DESC[2] = 0x62; /* dest[15:8] (FWDATA=0x6273) */
  DMA_DESC[3] = 0x73; /* dest[7:0] */
  DMA_DESC[4] = (uint8_t)((nbytes >> 8) & 0xff);
  DMA_DESC[5] = (uint8_t)(nbytes & 0xff);
  DMA_DESC[6] = 0x12; /* wordsize=0,tmode=0,trig=0x12 (FLASH) */
  DMA_DESC[7] = 0x42; /* srcinc=1,destinc=0,irqmask=1,m8=0,priority=2 */

  DMA1CFGL = 0x00; /* punta il canale DMA1 al descrittore a 0x0400 */
  DMA1CFGH = 0x04;

  DMAIRQ &= ~0x02;
  DMAARM &= ~0x02;

  DMAARM |= 0x02; /* arma il canale 1 */

  FCTL = 0x06; /* avvia la copia RAM->FLASH via DMA */

  i = 0;
  while (FCTL & 0x80) {
    i++;
    if (i == 0) break; /* timeout di sicurezza dopo 256 giri */
  }
}

/* Cancella una pagina da 1KB, RAM-resident - identica alla variante CPU
 * (ram_flash_write.c), l'erase non dipende dal metodo di scrittura
 * (DMA/CPU), e' sempre lo stesso registro FCTL. Vedi commento su
 * do_flash_erase() in ram_flash_write.c per il perche' serva girare
 * da RAM. */
uint8_t do_flash_erase(void)
{
  FADDRH = P_FADDRH;
  FADDRL = 0x00;
  FCTL = 0x01; /* ERASE=1 */
  while (FCTL & 0x80) { } /* aspetta BUSY */
  return (FCTL & 0x20) ? 1 : 0; /* ABORT */
}

void main(void)
{
  /* mai eseguito davvero - vedi commento in testa al file */
  do_flash_write();
  do_flash_erase();
  while (1) { }
}
