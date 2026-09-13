/* radio.h - point-to-point radio link on the CC2544 Link Layer Engine,
 * Auto Mode with hardware ACK/retransmit (TI's equivalent of Enhanced
 * ShockBurst).
 *
 * Not Logitech Unifying compatible: a single fixed pipe/address, no
 * encryption - but uses the same hardware reliability mechanism as the
 * real Logitech firmware (PRF_TASK_CONF Auto Mode + AA). See radio.c
 * for exact datasheet (TI SWRU283B) references.
 */
#ifndef RADIO_H
#define RADIO_H

#include <stdint.h>

/* Fixed payload length (address/header/CRC handled in hardware, not
 * counted here). Same value for TX and RX. */
#define RADIO_PKT_LEN 5

/* The declared length byte (TX FIFO, and PRF_ADDR_ENTRY0.RXLENGTH for
 * the RX role) must count the address byte the hardware auto-inserts
 * (PRF_PKT_CONF.ADDR_LEN=1), even though it never appears as an
 * explicit FIFO byte (RX/TX_ADDR_CONF=00) - with
 * RXLENGTH=RADIO_PKT_LEN(5) the length byte read back from the Rx FIFO
 * is always 4, truncating the last payload byte. */
#define RADIO_FRAME_LEN (RADIO_PKT_LEN + 1)

/* Fixed channel and 1-byte pipe address for this proprietary link -
 * arbitrary, not derived from Logitech pairing. Shared by app_tx and
 * app_rx via this header so they stay in sync by construction. */
#define RADIO_CHANNEL      42
#define RADIO_PIPE_ADDRESS 0xE7

/* Chip role - determines PRF_ADDR_ENTRY0.RXLENGTH: TX (radio_send())
 * listens for empty ACKs, RX (radio_recv_poll()) receives the real
 * payload. See radio_init() in radio.c. */
#define RADIO_ROLE_TX 1
#define RADIO_ROLE_RX 0

void radio_init(uint8_t role); /* RADIO_ROLE_TX or RADIO_ROLE_RX */

/* Blocking send: transmits buf (RADIO_PKT_LEN bytes) and waits for the
 * task to complete. Auto Mode waits for the ACK and retransmits in
 * hardware up to PRF_RETRANS_CNT times on its own. Returns 1 if the
 * task ended with TASK_ENDOK (ack received), 0 otherwise. Re-arms
 * receive automatically afterward. */
uint8_t radio_send(const uint8_t *buf);

/* Non-blocking: if a previously armed receive task has completed,
 * copies up to maxlen bytes into buf (the ACK is sent automatically by
 * hardware, no action needed here), re-arms receive immediately, and
 * returns the byte count copied (0 if the packet had an invalid CRC or
 * was a duplicate retransmission). Returns 0 without blocking if the
 * task is still in progress. Call continuously from the main loop. */
uint8_t radio_recv_poll(uint8_t *buf, uint8_t maxlen);

/* Diagnostics: out[0]=LLESTAT, out[1]=PRF_ENDCAUSE, out[2]=rx_armed,
 * out[3]=RSSI, out[4]=last length byte read from the Rx FIFO. */
void radio_debug_status(uint8_t *out);

/* How many rounds (whole Auto Mode tasks, each with up to
 * PRF_RETRANS_CNT hardware retries) the last radio_send() needed
 * before succeeding or exhausting RADIO_SEND_MAX_ROUNDS - 1 is the
 * normal case. Useful to measure how often the outer TASK_MAXRT retry
 * (see radio.c) actually kicks in, instead of trusting last_send_ok
 * alone (which only reflects whether TX got the ack, not whether RX
 * got the packet - the two can fail independently). */
uint8_t radio_last_send_rounds(void);

#endif
