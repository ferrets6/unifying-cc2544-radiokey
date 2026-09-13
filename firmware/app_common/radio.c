/* radio.c - see radio.h.
 *
 * Link Layer Engine Auto Mode (SWRU283B ch. 23): ack/retransmit handled
 * entirely in hardware, the same mechanism the real Logitech firmware
 * uses for this chip (PRF_TASK_CONF=0x86 in the disassembly - MODE=10
 * Auto Mode, see logitech_stock_firmware/README.md). The datasheet
 * (line 186) describes "extensive baseband automation, including
 * auto-acknowledgement" as the intended reliability mechanism for this
 * hardware, as an alternative to software retry logic.
 *
 * Register addresses (references/swru283b_raw.txt):
 *  - normal XREG (0x6180-0x61FF): FRMCTRL0=0x6180, LLESTAT=0x6188,
 *    RSSI=0x618E, MDMCTRL0-3=0x6190-0x6193, BSP_P0..P3=0x61E0-0x61E3,
 *    LLECTRL=0x61B1, RFRAMCFG=0x61C0, RFFCFG=0x61C6, BSP_MODE=0x61E9,
 *    SW_CONF/SW0-3=0x6194-0x6198.
 *  - RAM-based registers, page 0 (Table 23-4): PRF_CHAN=0x6000,
 *    PRF_TASK_CONF=0x6001, PRF_FIFO_CONF=0x6002, PRF_PKT_CONF=0x6003,
 *    PRF_CRC_LEN=0x6004, PRF_CRC_INIT=0x6008-0x600B,
 *    PRF_RETRANS_CNT=0x600D, PRF_RETRANS_DELAY=0x6010-0x6011,
 *    PRF_SEARCH_TIME=0x6012-0x6013, PRF_RX_TX_TIME=0x6014-0x6015,
 *    PRF_TX_RX_TIME=0x6016-0x6017, PRF_ADDR_ENTRY0=0x6018-0x6023 (12
 *    bytes, Auto Mode layout per Table 23-5 - different from Basic
 *    Mode's 3-byte layout), PRF_ENDCAUSE=0x607F.
 *  - direct SFR: RFST=0xE1, RFD=0xD9.
 *
 * PRF_CRC_INIT (RAM-based, "no defined reset value, must be
 * initialized by the MCU" per the datasheet) depends on the CRC
 * polynomial in BSP_P0..P3: for CRC-16-CCITT (Table 23-9, our
 * BSP_P0..P3=00,00,21,10) the correct value is 00,00,FF,FF.
 *
 * Auto Mode design choices:
 *  - PRF_TASK_CONF = 0x02 (MODE=10 Auto Mode, 9-bit header, REPEAT=0 -
 *    one packet/ack per call, re-armed from C after each task, instead
 *    of Logitech's REPEAT=1 which keeps the task always active).
 *  - PRF_ADDR_ENTRY0.CONF (Auto Mode layout) = ENA0=1, AA=1 (the bit
 *    that turns on ack/retransmit), VARLEN=0 (fixed length).
 *  - PRF_ADDR_ENTRY0.RXLENGTH depends on role (see radio_init()): RX
 *    expects the real payload (RADIO_FRAME_LEN), TX expects an empty
 *    ack (the address is auto-inserted and doesn't count toward
 *    RXLENGTH in Auto Mode - see the PRF_ADDR_ENTRY0_RXLEN comment
 *    below).
 *  - PRF_RETRANS_CNT, PRF_RETRANS_DELAY, PRF_SEARCH_TIME,
 *    PRF_TX_RX_TIME, PRF_RX_TX_TIME: taken directly from the real
 *    Logitech stock firmware for this chip (read from the disassembly
 *    in logitech_stock_firmware/full_disasm.txt), not approximated -
 *    see the comment in radio_init() for detail.
 */
#include "radio.h"

#define XREG(addr) (*(volatile __xdata uint8_t *)(addr))

/* RAM-based registers, page 0 (RFRAMCFG.PRE default) */
#define PRF_CHAN            XREG(0x6000)
#define PRF_TASK_CONF       XREG(0x6001)
#define PRF_FIFO_CONF       XREG(0x6002)
#define PRF_PKT_CONF        XREG(0x6003)
#define PRF_CRC_LEN         XREG(0x6004)
#define PRF_CRC_INIT0       XREG(0x6008)
#define PRF_CRC_INIT1       XREG(0x6009)
#define PRF_CRC_INIT2       XREG(0x600A)
#define PRF_CRC_INIT3       XREG(0x600B)
#define PRF_RETRANS_CNT     XREG(0x600D)
#define PRF_RETRANS_DELAY_L XREG(0x6010)
#define PRF_RETRANS_DELAY_H XREG(0x6011)
#define PRF_SEARCH_TIME_L   XREG(0x6012)
#define PRF_SEARCH_TIME_H   XREG(0x6013)
#define PRF_RX_TX_TIME_L    XREG(0x6014)
#define PRF_RX_TX_TIME_H    XREG(0x6015)
#define PRF_TX_RX_TIME_L    XREG(0x6016)
#define PRF_TX_RX_TIME_H    XREG(0x6017)
/* PRF_ADDR_ENTRY0, Auto Mode layout (Table 23-5) - 12 bytes, different
 * from Basic Mode's 3-byte layout. */
#define PRF_ADDR_ENTRY0_CONF      XREG(0x6018)
#define PRF_ADDR_ENTRY0_RXLEN     XREG(0x6019)
#define PRF_ADDR_ENTRY0_ADDR      XREG(0x601A)
#define PRF_ADDR_ENTRY0_SEQSTAT   XREG(0x601B)
#define PRF_ADDR_ENTRY0_ACKLEN0   XREG(0x601C)
#define PRF_ADDR_ENTRY0_ACKLEN1   XREG(0x601D)
#define PRF_RADIO_CONF      XREG(0x607E)
#define PRF_ENDCAUSE        XREG(0x607F)

/* normal XREG */
#define FRMCTRL0  XREG(0x6180)
#define LLESTAT   XREG(0x6188)
#define RSSI_REG  XREG(0x618E)
#define MDMCTRL0  XREG(0x6190)
#define MDMCTRL1  XREG(0x6191)
#define MDMCTRL2  XREG(0x6192)
#define MDMCTRL3  XREG(0x6193)
#define BSP_P0    XREG(0x61E0)
#define BSP_P1    XREG(0x61E1)
#define BSP_P2    XREG(0x61E2)
#define BSP_P3    XREG(0x61E3)
#define LLECTRL   XREG(0x61B1)
#define SEMAPHORE0 XREG(0x618A)
#define SEMAPHORE1 XREG(0x618B)
#define RFRAMCFG  XREG(0x61C0)
#define RFFCFG    XREG(0x61C6)
#define BSP_MODE  XREG(0x61E9)
#define SW_CONF   XREG(0x6194)
#define SW0       XREG(0x6195)
#define SW1       XREG(0x6196)
#define SW2       XREG(0x6197)
#define SW3       XREG(0x6198)
#define MDMTEST0  XREG(0x61A5)

/* direct SFR */
__sfr __at(0xD9) RFD;
__sfr __at(0xE1) RFST;

#define LLESTAT_LLE_IDLE 0x04

/* RFST: FIFO commands (Table 23-2, always issuable) */
#define CMD_RXFIFO_RESET  0x81
#define CMD_TXFIFO_RESET  0x91
#define CMD_TXFIFO_COMMIT 0x95

/* RFST: LLE commands (Table 23-12, only when LLESTAT.LLE_IDLE=1) */
#define CMD_RX 0x08
#define CMD_TX 0x09

#define TASK_ENDOK 0

static uint8_t rx_armed;
static uint8_t last_len_byte; /* diagnostics: last length byte read from the Rx FIFO */

static void wait_idle(void) {
    while (!(LLESTAT & LLESTAT_LLE_IDLE)) {
        ;
    }
}

static void wait_rfst_clear(void) {
    while (RFST != 0) {
        ;
    }
}

static void radio_arm_rx(void) {
    wait_idle();
    RFST = CMD_RXFIFO_RESET;
    wait_rfst_clear();
    PRF_CHAN = RADIO_CHANNEL; /* bit7 SYNTH_ON=0: turns off the synth at task end */
    RFST = CMD_RX;
    rx_armed = 1;
}

void radio_init(uint8_t role) {
    RFRAMCFG = 0x00; /* page 0 (reset default) */

    /* Force a real LLE reset before re-enabling it, instead of just
     * writing LLE_EN=1 (a no-op if already 1). After an APP_RESTART
     * (software jump to 0x0400, no hardware reset) a listening task
     * left running by the previous instance stays that way - for the
     * RX role, which listens with PRF_SEARCH_TIME=0 "never give up"
     * (see below), the LLE is almost always non-idle in normal
     * conditions. wait_idle() below would then block forever,
     * triggering the emergency watchdog into the bootloader. LLE_EN=0
     * is the "in reset" default (SWRU283B): power-cycling the LLE
     * aborts any running task, guaranteeing wait_idle() always finds a
     * clean state, whether after a real hardware reset (LLECTRL is
     * already 0, rewriting it is a no-op) or after an APP_RESTART.
     *
     * Toggling LLECTRL alone isn't enough: SEMAPHORE0/SEMAPHORE1
     * (0x618A/0x618B, SWRU283B 23.3.3) are taken by the LLE at task
     * start and released by the LLE itself only at the task's natural
     * end. Force-aborting a task (disabling LLECTRL instead of letting
     * it finish) leaves them held forever - the next CMD_RX in
     * radio_arm_rx() fails with PRF_ENDCAUSE=0xFD (TASKERR_SEM,
     * "Unable to obtain semaphore", Table 23-14): radio goes silent, no
     * hang. Released by writing 1 (R/W1, 23.4.1) - safe even when
     * already free (write-1-to-set, not toggle) or after a real
     * hardware reset. */
    LLECTRL = 0x00;
    SEMAPHORE0 = 0x01;
    SEMAPHORE1 = 0x01;
    LLECTRL = 0x01; /* LLE_EN=1: enable the Link Layer Engine (default: in reset) */
    wait_idle();

    BSP_MODE = 0x00; /* W_PN7_EN=0, W_PN9_EN=0: whitening disabled */

    MDMCTRL1 = 0x48; /* FOC_MODE=01 (default), CORR_THR=8 (0.25*32bit, SWRU283B) */
    /* The Auto Mode ack needs these four points set together - none is
     * sufficient alone. The ack is the shortest possible packet (0 real
     * payload) and the fastest turnaround in the protocol (RX right
     * after receiving), so the least tolerant of degraded demodulation:
     * a normal 5-byte data packet has enough margin to pass the CRC
     * despite these gaps, the ack doesn't.
     *
     * 1) MDMCTRL2.SW_BIT_ORDER must match FRMCTRL0.ENDIANNESS (23.8:
     *    "Normally, FRMCTRL0.ENDIANNESS and MDMCTRL2.SW_BIT_ORDER
     *    should have the same value") - here ENDIANNESS=1 (required in
     *    Auto Mode) so SW_BIT_ORDER=1.
     * 2) PRF_PKT_CONF.AGC_EN=1 (below) needs extra preamble before the
     *    packet for the AGC to converge (23.9.2.1) - set via
     *    MDMCTRL2.NUM_PREAM_BYTES.
     * 3) MDMTEST0.RSSI_ACC governs the RSSI averaging window the AGC
     *    uses - the extra preamble length needed in point 2 depends on
     *    this value ("(n+1)*tRSSI"), so it must be chosen together with
     *    NUM_PREAM_BYTES, not separately.
     * 4) PRF_RADIO_CONF.TXIF (23.5) governs the intermediate frequency
     *    offset in TX at 2Mbps - the datasheet recommends +-1 MHz;
     *    left unwritten it's an undefined RAM value.
     *
     * A fifth point, in PRF_ADDR_ENTRY0_RXLEN below, is needed together
     * with these four, not as an alternative.
     *
     * Values (1-4) taken directly from the real Logitech stock firmware
     * for this same chip (RQR24.07, disassembled in
     * logitech_stock_firmware/full_disasm.txt). */
    MDMCTRL2 = 0xCC; /* SW_BIT_ORDER=1, DEM_PREAM_MODE=1, NUM_PREAM_BYTES=12 extra (13 total) */
    MDMTEST0 = 0x6F; /* RSSI_ACC=011 (average of 4 windows of 5.33us) */
    PRF_RADIO_CONF = 0x10; /* TXIF=01 (+-1MHz, recommended at 2Mbps) */
    MDMCTRL3 = 0x60; /* SYNC_MODE=01 (strict: threshold + exact decode), RAMP_AMP=1 (default) */
    RFFCFG = 0x23;   /* TXAUTOCOMMIT=1 (default), RXAUTOCOMMIT=1, RXFAUTODEALLOC=1 */

    FRMCTRL0 = 0x43; /* SW_CRC_MODE=1, ENDIANNESS=1 (required in Auto Mode) */
    MDMCTRL0 = 0x0E; /* MODULATION=0111 on bits 4:1 = 2Mbps GFSK, 320kHz deviation */
    BSP_P0 = 0x00;   /* CRC-16-CCITT polynomial (Table 23-9) */
    BSP_P1 = 0x00;
    BSP_P2 = 0x21;
    BSP_P3 = 0x10;

    /* PRF_CRC_INIT (RAM-based) has no defined reset value - for the
     * CRC-16-CCITT row of Table 23-9 (our BSP_P0..P3) the correct
     * value is 00,00,FF,FF. */
    PRF_CRC_INIT0 = 0x00;
    PRF_CRC_INIT1 = 0x00;
    PRF_CRC_INIT2 = 0xFF;
    PRF_CRC_INIT3 = 0xFF;

    SW_CONF = 0x00; /* DUAL_RX=0, SW_LEN=00000 (32 bit) */
    SW0 = 0xE7;
    SW1 = 0x7E;
    SW2 = 0x1C;
    SW3 = 0xB4;

    PRF_PKT_CONF = 0x03;  /* ADDR_LEN=1, AGC_EN=1 (recommended at 2Mbps), START_TONE=0 */
    PRF_CRC_LEN = 0x02;   /* CRC-16 */
    PRF_FIFO_CONF = 0x06; /* AUTOFLUSH_CRC=1, AUTOFLUSH_EMPTY=1, RX/TX_ADDR_CONF=00 */

    /* MODE=10 (Auto Mode, 9-bit header - payload up to 63 bytes, well
     * over our 5), REPEAT=0 (one task per call, re-armed from C). */
    PRF_TASK_CONF = 0x02;

    /* Retry/turnaround timing taken directly from the real Logitech
     * stock firmware for this chip (same disassembly cited above):
     *  - RETRANS_CNT=15, RETRANS_DELAY~=952us.
     *  - TX: SEARCH_TIME~=50us, TX_RX_TIME~=52.5us before starting the
     *    ack search.
     *  - RX: RX_TX_TIME~=44.9us before sending the ack. */
    PRF_RETRANS_CNT = 15; /* 0x0F */
    PRF_RETRANS_DELAY_L = 0x80; /* 15232 = 0x3B80, ~952us */
    PRF_RETRANS_DELAY_H = 0x3B;
    if (role == RADIO_ROLE_TX) {
        PRF_SEARCH_TIME_L = 0x40; /* 1600 = 0x0640, ~50us */
        PRF_SEARCH_TIME_H = 0x06;
        PRF_RX_TX_TIME_L = 0x00; /* unused on TX (RX task only) */
        PRF_RX_TX_TIME_H = 0x00;
        PRF_TX_RX_TIME_L = 0x80; /* 1664 = 0x0680, ~52.5us */
        PRF_TX_RX_TIME_H = 0x06;
    } else {
        PRF_SEARCH_TIME_L = 0x00; /* 0 = never give up, RX always keeps listening */
        PRF_SEARCH_TIME_H = 0x00;
        PRF_RX_TX_TIME_L = 0x9C; /* 1436 = 0x059C, ~44.9us */
        PRF_RX_TX_TIME_H = 0x05;
        PRF_TX_RX_TIME_L = 0x00; /* unused on RX (TX task only) */
        PRF_TX_RX_TIME_H = 0x00;
    }

    /* Auto Mode CONF layout (Table 23-5): bit0 ENA0=1 (match primary
     * sync word, needed on RX), bit1 ENA1=0, bit2 REUSE=0 (the LLE
     * deallocates on its own), bit3 AA=1 (turns on auto ack/retransmit
     * - the whole point of Auto Mode), bit4 VARLEN=0 (fixed length),
     * bit5 FIXEDSEQ=0 (the LLE manages the sequence number itself),
     * bit6 TXLEN=0 (inserts the real length in the header, ignored by
     * a VARLEN=0 receiver anyway). */
    PRF_ADDR_ENTRY0_CONF = 0x09; /* ENA0=1, AA=1 */
    PRF_ADDR_ENTRY0_ADDR = RADIO_PIPE_ADDRESS;
    PRF_ADDR_ENTRY0_SEQSTAT = 0x00;  /* VALID=0: the next packet received is always treated as new */
    PRF_ADDR_ENTRY0_ACKLEN0 = 0x00;  /* ack with no payload (just the auto-inserted address) */
    PRF_ADDR_ENTRY0_ACKLEN1 = 0x00;

    /* RXLENGTH depends on role: RX receives the real payload
     * (RADIO_FRAME_LEN, address byte included for the same empirical
     * reason as Basic Mode - see radio.h).
     *
     * TX, listening for the ack after transmitting, expects an empty
     * ack. The Basic Mode convention (address counted in the declared
     * length) doesn't apply here: Auto Mode field order is different
     * (Figure 23-6 vs 23-7) - Basic Mode is
     * Length->Address->Payload (address counts in the declared
     * length), Auto Mode is Address->Header->Payload (address comes
     * before the header/length, so it doesn't count in RXLENGTH,
     * defined by the datasheet as "the number of bytes after the
     * header and before the CRC"). For an empty ack on TX, RXLENGTH is
     * therefore 0, not 1. */
    if (role == RADIO_ROLE_TX) {
        PRF_ADDR_ENTRY0_RXLEN = 0;
    } else {
        PRF_ADDR_ENTRY0_RXLEN = RADIO_FRAME_LEN;
    }

    radio_arm_rx();
}

/* After a TASK_MAXRT (PRF_RETRANS_CNT hardware retries exhausted with
 * no ack) the packet isn't discarded by the LLE - the datasheet
 * (23.9.2.4.2) is explicit: "a retry Tx FIFO command is sent before the
 * task ends, and PRF_ADDR_ENTRYn.SEQSTAT.SEQ is not incremented. This
 * means that by default, the packet is attempted retransmitted in the
 * next task" - the packet stays queued with the same sequence number,
 * so reissuing CMD_TX retries it, and RX (if it had already received
 * one of the earlier attempts but lost the ack) correctly recognizes it
 * as the same packet via SEQSTAT.SEQ+CRC (23.9.2.3.2) instead of
 * treating it as new.
 *
 * radio_send() relies on this: on TASK_MAXRT it retries by reissuing
 * CMD_TX without touching the queue (no reset, no rewrite) for a
 * limited number of extra rounds, instead of giving up on the first
 * TASK_MAXRT. Each round is a whole Auto Mode task (up to
 * PRF_RETRANS_CNT hardware retries included), so the total retry
 * budget grows a lot for a negligible time cost (blocking, but on the
 * order of milliseconds worst case, well under the ~1s emergency
 * watchdog). */
#define RADIO_SEND_MAX_ROUNDS 4

static uint8_t send_rounds_used;

uint8_t radio_last_send_rounds(void) {
    return send_rounds_used;
}

uint8_t radio_send(const uint8_t *buf) {
    uint8_t i, ok, round;

    RFST = CMD_TXFIFO_RESET;
    wait_rfst_clear();
    RFD = RADIO_FRAME_LEN; /* see the note in radio.h about the +1 for the address byte */
    for (i = 0; i < RADIO_PKT_LEN; i++) {
        RFD = buf[i];
    }
    RFST = CMD_TXFIFO_COMMIT;
    wait_rfst_clear();

    PRF_CHAN = RADIO_CHANNEL;

    ok = 0;
    for (round = 0; round < RADIO_SEND_MAX_ROUNDS && !ok; round++) {
        RFST = CMD_TX;
        /* In Auto Mode the task covers transmit + ack wait + any
         * automatic hardware retransmissions (up to PRF_RETRANS_CNT) -
         * can take longer than a plain send. */
        wait_idle();
        ok = (PRF_ENDCAUSE == TASK_ENDOK);
        /* on TASK_MAXRT (ok=0) the queue is left untouched - same
         * packet, same SEQSTAT.SEQ, ready for another round with just
         * a new CMD_TX (see comment above); any other outcome exits
         * the loop regardless (ok=1, or the last round used up). */
    }
    send_rounds_used = round;

    rx_armed = 0;
    radio_arm_rx(); /* always go back to listening after a send */

    return ok;
}

uint8_t radio_recv_poll(uint8_t *buf, uint8_t maxlen) {
    uint8_t n, i;

    if (!rx_armed) {
        return 0;
    }
    if (!(LLESTAT & LLESTAT_LLE_IDLE)) {
        return 0; /* task still running, nothing ready */
    }

    rx_armed = 0;
    n = 0;
    if (PRF_ENDCAUSE == TASK_ENDOK) {
        /* the ack (if due) was already sent automatically by hardware
         * before the task ended - no action needed here beyond reading
         * the received payload. */
        last_len_byte = RFD; /* length byte, discarded */
        n = RADIO_PKT_LEN;
        if (n > maxlen) {
            n = maxlen;
        }
        for (i = 0; i < n; i++) {
            buf[i] = RFD;
        }
    }

    radio_arm_rx();
    return n;
}

void radio_debug_status(uint8_t *out) {
    out[0] = LLESTAT;
    out[1] = PRF_ENDCAUSE;
    out[2] = rx_armed;
    out[3] = RSSI_REG;
    out[4] = last_len_byte;
}
