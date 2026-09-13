; BOOTLOADER - the firmware actually flashed in page 0 (0x0000-0x03FF)
; of the dongle, hand-written 8051 assembly (sdas8051/sdcc). Exposes a
; minimal USB protocol to write a new firmware/app at 0x0400+ (see
; tools/flash_firmware.py) and, via bootloader_updater.asm, to safely
; rewrite itself.
;
; Reads SLEEPSTA.RST (SFR 0x9D, bit 4:3 - TI SWRU283B: "00: Power-on
; reset and brownout detection, 01: External reset, 10: Watchdog Timer
; reset, 11: Clock loss reset") to decide behavior. A real power-on
; jumps straight to the app at 0x0400, no visible window - same as the
; real Logitech bootloader. Any other cause (external reset via debug
; clip, app SOFT_RESET via watchdog, or a real hang caught by the same
; watchdog) opens an indefinite listening window - exits only via
; FLASH_FINISHED and only if the status is OK: a mismatch never jumps to
; the app unconditionally, it stays listening (never jump to a
; potentially half-written app). Own VID:PID (1209:0010), separate from
; bootloader_updater (1209:0020) and app_tx/app_rx (1209:0030) as
; Logitech itself does - a PID shared between bootloader and app risks a
; real conflict between the WinUSB and native Windows HID drivers when
; the same dongle changes shape (bootloader vendor-only <-> app_rx HID).
; Wide spacing (0x10) so the three stages are never confused. See
; README.md for the full protocol.

	.module bootloader
	.area HOME (CODE)

SLEEPSTA	=	0x9D		; last reset cause, bit 4:3 = RST[1:0]
CLKCONCMD	=	0x70C6
CLKCONSTA	=	0x709E
USBINDEX	=	0x620E
USBCTRL		=	0x620F
USBCS0		=	0x6211
USBCNT0		=	0x6216
USBF0		=	0x6220
USBADDR		=	0x6200
TR0		=	0x624B
FCTL		=	0x6270
FADDRL		=	0x6271
FADDRH		=	0x6272
FWDATA		=	0x6273
MEMCTR		=	0x70C7

P_FADDRH	=	0x0200
P_FADDRL	=	0x0201
P_NWORDS_HI	=	0x0202
P_NWORDS_LO	=	0x0203
P_DATA		=	0x0210

; Flash session state (FLASH_STARTED/FLASH_FINISHED) - internal RAM,
; NOT xdata: these addresses in XDATA hold the ram_routine copy (see
; copyloop below), an movx here would corrupt it before it even runs.
FLASHING_ACTIVE	=	0x20
EXPECTED_LEN_LO	=	0x21
EXPECTED_LEN_HI	=	0x22
WRITTEN_LEN_LO	=	0x23
WRITTEN_LEN_HI	=	0x24

APP_BASE	=	0x0400
RAM_BASE_CODE	=	0x8000

;=========================================================
_start::
	mov	dptr,#0x0140
	mov	a,#0xC1
	movx	@dptr,a

	mov	dptr,#CLKCONCMD
	mov	a,#0x80
	movx	@dptr,a
clkwait:
	mov	dptr,#CLKCONSTA
	movx	a,@dptr
	cjne	a,#0x80,clkwait

	mov	dptr,#USBCTRL
	mov	a,#0x03
	movx	@dptr,a
	mov	dptr,#TR0
	movx	a,@dptr
	anl	a,#0xFB
	movx	@dptr,a
pllwait:
	mov	dptr,#USBCTRL
	movx	a,@dptr
	anl	a,#0x80
	jz	pllwait
	mov	dptr,#USBCTRL
	movx	a,@dptr
	orl	a,#0x08
	movx	@dptr,a

	mov	r2,#<ram_routine
	mov	r3,#>ram_routine
	mov	r4,#0x00
	mov	r5,#0x00
	mov	r6,#<(ram_routine_end - ram_routine)
	mov	r7,#>(ram_routine_end - ram_routine)
copyloop:
	mov	dpl,r2
	mov	dph,r3
	clr	a
	movc	a,@a+dptr
	mov	dpl,r4
	mov	dph,r5
	movx	@dptr,a
	inc	r2
	mov	a,r2
	jnz	copy_nc1
	inc	r3
copy_nc1:
	inc	r4
	mov	a,r4
	jnz	copy_nc2
	inc	r5
copy_nc2:
	djnz	r6,copyloop
	mov	a,r7
	jz	copy_done
	dec	r7
	sjmp	copyloop
copy_done:
	mov	dptr,#0x0140
	mov	a,#0xC2
	movx	@dptr,a

	; real power-on (SLEEPSTA.RST==00) -> jump straight to the app.
	; Any other reset cause falls through to the listening window below.
	mov	a,SLEEPSTA
	anl	a,#0x18
	jnz	not_power_on
	ljmp	APP_BASE
not_power_on:

	; indefinite listening window: only exit is FLASH_FINISHED, no timeout
	mov	FLASHING_ACTIVE,#1
window_inner:
	lcall	usb_poll
	mov	a,FLASHING_ACTIVE
	jnz	window_inner
	ljmp	APP_BASE

;=========================================================
usb_poll:
	mov	dptr,#USBINDEX
	clr	a
	movx	@dptr,a
	mov	dptr,#USBCS0
	movx	a,@dptr
	anl	a,#0x01
	jz	poll_ret

	push	dpl
	push	dph
	push	acc
	mov	dptr,#0x0141
	mov	a,#0xD0
	movx	@dptr,a
	pop	acc
	pop	dph
	pop	dpl

	mov	dptr,#USBF0
	movx	a,@dptr
	mov	r1,a
	movx	a,@dptr
	mov	r2,a
	movx	a,@dptr
	mov	r3,a
	movx	a,@dptr
	mov	r4,a
	movx	a,@dptr
	movx	a,@dptr
	movx	a,@dptr
	mov	r5,a
	movx	a,@dptr
	mov	r6,a

	mov	dptr,#0x0142
	mov	a,r1
	movx	@dptr,a
	mov	dptr,#0x0143
	mov	a,r2
	movx	@dptr,a

	mov	a,r1
	anl	a,#0x60
	xrl	a,#0x40
	jnz	dispatch_standard

	mov	a,r2
	cjne	a,#0x01,chk_write
	ljmp	handle_erase_page
chk_write:
	cjne	a,#0x02,chk_flash_started
	ljmp	handle_write_chunk
chk_flash_started:
	cjne	a,#0x04,chk_flash_finished
	ljmp	handle_flash_started
chk_flash_finished:
	cjne	a,#0x05,do_stall
	ljmp	handle_flash_finished

dispatch_standard:
	mov	a,r2
	cjne	a,#0x06,chk_setaddr
	ljmp	handle_get_descriptor
chk_setaddr:
	cjne	a,#0x05,chk_setconf
	mov	dptr,#USBCS0
	mov	a,#0x48
	movx	@dptr,a
	mov	a,r3
	anl	a,#0x7F
	mov	dptr,#USBADDR
	movx	@dptr,a
	sjmp	poll_ret
chk_setconf:
	cjne	a,#0x09,do_stall
	mov	dptr,#USBCS0
	mov	a,#0x48
	movx	@dptr,a
	sjmp	poll_ret
do_stall:
	mov	dptr,#USBCS0
	mov	a,#0x40
	movx	@dptr,a
	mov	a,#0x20
	movx	@dptr,a
poll_ret:
	ret

;=========================================================
handle_erase_page:
	mov	dptr,#USBCS0
	mov	a,#0x48
	movx	@dptr,a

	mov	dptr,#P_FADDRH
	mov	a,r3
	movx	@dptr,a

	mov	dptr,#MEMCTR
	movx	a,@dptr
	orl	a,#0x08
	movx	@dptr,a

	lcall	RAM_BASE_CODE + erase_entry_off

	mov	dptr,#MEMCTR
	movx	a,@dptr
	anl	a,#0xF7
	movx	@dptr,a

	ljmp	poll_ret

;=========================================================
handle_write_chunk:
	mov	dptr,#USBCS0
	mov	a,#0x40
	movx	@dptr,a

	mov	r0,#<P_DATA
	mov	r1,#>P_DATA
	mov	a,r5
	mov	r7,a
recv_wait:
	mov	dptr,#USBINDEX
	clr	a
	movx	@dptr,a
	mov	dptr,#USBCS0
	movx	a,@dptr
	anl	a,#0x01
	jz	recv_wait
	mov	dptr,#USBCNT0
	movx	a,@dptr
	mov	r2,a
	mov	dptr,#USBF0
recv_byte:
	mov	a,r2
	jz	recv_pkt_done
	movx	a,@dptr
	push	acc
	mov	dpl,r0
	mov	dph,r1
	pop	acc
	movx	@dptr,a
	inc	r0
	mov	a,r0
	jnz	recv_nc
	inc	r1
recv_nc:
	dec	r7
	mov	dptr,#USBF0
	dec	r2
	sjmp	recv_byte
recv_pkt_done:
	mov	a,r7
	jnz	recv_more
	mov	dptr,#USBCS0
	mov	a,#0x48
	movx	@dptr,a
	sjmp	do_write
recv_more:
	mov	dptr,#USBCS0
	mov	a,#0x40
	movx	@dptr,a
	sjmp	recv_wait

do_write:
	; WRITTEN_LEN += wLength (r5:r6), for the FLASH_FINISHED check
	mov	a,WRITTEN_LEN_LO
	add	a,r5
	mov	WRITTEN_LEN_LO,a
	mov	a,WRITTEN_LEN_HI
	addc	a,r6
	mov	WRITTEN_LEN_HI,a

	clr	c
	mov	a,r4
	rrc	a
	mov	r4,a
	mov	a,r3
	rrc	a
	mov	r3,a
	clr	c
	mov	a,r4
	rrc	a
	mov	r4,a
	mov	a,r3
	rrc	a
	mov	r3,a
	mov	dptr,#P_FADDRH
	mov	a,r4
	movx	@dptr,a
	mov	dptr,#P_FADDRL
	mov	a,r3
	movx	@dptr,a

	clr	c
	mov	a,r6
	rrc	a
	mov	r6,a
	mov	a,r5
	rrc	a
	mov	r5,a
	clr	c
	mov	a,r6
	rrc	a
	mov	r6,a
	mov	a,r5
	rrc	a
	mov	r5,a
	mov	dptr,#P_NWORDS_HI
	mov	a,r6
	movx	@dptr,a
	mov	dptr,#P_NWORDS_LO
	mov	a,r5
	movx	@dptr,a

	mov	dptr,#MEMCTR
	movx	a,@dptr
	orl	a,#0x08
	movx	@dptr,a

	lcall	RAM_BASE_CODE

	mov	dptr,#MEMCTR
	movx	a,@dptr
	anl	a,#0xF7
	movx	@dptr,a

	ljmp	poll_ret

;=========================================================
; FLASH_STARTED (bRequest 0x04, OUT no data): declares the start of a
; write session. wValue (r3:r4) = total bytes the host intends to write
; (sum of all WRITE_CHUNKs to follow). Disables the listening window's
; timeout until FLASH_FINISHED.
;=========================================================
handle_flash_started:
	mov	FLASHING_ACTIVE,#1
	mov	EXPECTED_LEN_LO,r3
	mov	EXPECTED_LEN_HI,r4
	mov	WRITTEN_LEN_LO,#0
	mov	WRITTEN_LEN_HI,#0
	mov	dptr,#USBCS0
	mov	a,#0x48			; ack (no data)
	movx	@dptr,a
	ljmp	poll_ret

;=========================================================
; FLASH_FINISHED (bRequest 0x05, IN 1 byte): compares WRITTEN_LEN
; against EXPECTED_LEN, replies 0x00 (OK) or 0x01 (mismatch). Jumps to
; APP_BASE only if OK - a mismatch stays listening instead (never jump
; to a possibly half-written app).
;=========================================================
handle_flash_finished:
	mov	r2,WRITTEN_LEN_LO
	mov	r3,WRITTEN_LEN_HI
	mov	r4,EXPECTED_LEN_LO
	mov	r5,EXPECTED_LEN_HI
	mov	r6,#0x00		; r6 = status byte, 0x00 = OK
	; CJNE A,Rn isn't a valid 8051 addressing mode - compare via XRL
	; instead (0 result only if all bits match)
	mov	a,r2
	xrl	a,r4
	jnz	ff_mismatch
	mov	a,r3
	xrl	a,r5
	jnz	ff_mismatch
	sjmp	ff_send
ff_mismatch:
	mov	r6,#0x01
ff_send:
	mov	dptr,#USBCS0
	mov	a,#0x40			; CLR_OUTPKT_RDY (nessuna fase OUT)
	movx	@dptr,a
	mov	dptr,#USBF0
	mov	a,r6
	movx	@dptr,a			; status byte
	mov	dptr,#USBCS0
	mov	a,#0x0A			; INPKT_RDY|DATA_END
	movx	@dptr,a
ff_txwait:
	; wait for hardware confirmation the SIE actually sent the status packet
	movx	a,@dptr
	anl	a,#0x02
	jnz	ff_txwait
	mov	a,r6
	jz	ff_jump_app
	mov	FLASHING_ACTIVE,#1		; mismatch: keep listening
	ljmp	poll_ret
ff_jump_app:
	mov	FLASHING_ACTIVE,#0

	; Force a clean USB disconnect/reconnect before jumping: the host
	; still has this bootloader's session live (SET_ADDRESS already
	; done) - jumping without touching USB, whatever we jump to (ours or
	; third-party) may answer with different descriptors on a session
	; the host still thinks is valid, with no disconnect event to make
	; it re-enumerate. Confirmed live: a third-party firmware jumped to
	; directly from here never enumerated, only worked after a real
	; power-on. Same idea as usb_core_init()'s APP_RESTART path, trimmed
	; down to fit page 0 (no PLL_LOCKED re-poll needed, clock was never
	; touched). Double-counter delay to match the order of magnitude of
	; the already-proven delay_loop(20000) in usb_core.c.
	mov	dptr,#USBCTRL
	clr	a
	movx	@dptr,a
	mov	r1,#200
ff_usb_disc_wait:
	mov	r0,#0
ff_usb_disc_wait_inner:
	djnz	r0,ff_usb_disc_wait_inner
	djnz	r1,ff_usb_disc_wait
	mov	dptr,#USBCTRL
	mov	a,#0x0B			; USB_EN=1, PLL_EN=1, bit3=1 (pull-up)
	movx	@dptr,a
	mov	dptr,#USBADDR
	clr	a
	movx	@dptr,a

	ljmp	APP_BASE

;=========================================================
handle_get_descriptor:
	mov	dptr,#USBCS0
	mov	a,#0x40
	movx	@dptr,a

	mov	a,r4
	cjne	a,#0x01,gd_try_cfg
	mov	dptr,#device_descriptor
	sjmp	gd_send
gd_try_cfg:
	cjne	a,#0x02,gd_try_string
	mov	dptr,#config_descriptor
	sjmp	gd_send
gd_try_string:
	cjne	a,#0x03,gd_stall
	; STRING descriptor: index in r3 (wValueL) - 0=LANGID, 2=product
	; (no iManufacturer, no room in page 0 for both). Unlike device/
	; config (always 18 bytes, gd_send assumes that) strings vary in
	; length, so this path computes the real table length first.
	mov	a,r3
	cjne	a,#0x00,gd_str_try2
	mov	dptr,#string_lang
	mov	r7,#4
	sjmp	gd_str_clamp
gd_str_try2:
	cjne	a,#0x02,gd_stall
	mov	dptr,#string_product
	mov	r7,#(string_product_end-string_product)
gd_str_clamp:
	; send min(table length, wLength) bytes - wLength always < 256 here,
	; wLengthH (r6) ignored on purpose
	mov	a,r5
	clr	c
	subb	a,r7
	jnc	gd_str_send
	mov	a,r5
	mov	r7,a
gd_str_send:
	mov	r2,dpl
	mov	r3,dph
	sjmp	gd_copy
gd_stall:
	mov	dptr,#USBCS0
	mov	a,#0x20
	movx	@dptr,a
	ljmp	poll_ret

gd_send:
	mov	r2,dpl
	mov	r3,dph
	mov	a,r6
	jnz	gd_len18
	mov	a,r5
	clr	c
	subb	a,#18
	jc	gd_lenW
gd_len18:
	mov	r7,#18
	sjmp	gd_copy
gd_lenW:
	mov	a,r5
	mov	r7,a
gd_copy:
	mov	dptr,#USBF0
gd_loop:
	mov	a,r7
	jz	gd_fin
	mov	dpl,r2
	mov	dph,r3
	clr	a
	movc	a,@a+dptr
	push	acc
	mov	dptr,#USBF0
	pop	acc
	movx	@dptr,a
	inc	r2
	mov	a,r2
	jnz	gd_nc
	inc	r3
gd_nc:
	dec	r7
	sjmp	gd_loop
gd_fin:
	mov	dptr,#USBCS0
	mov	a,#0x0A
	movx	@dptr,a
	ljmp	poll_ret

;=========================================================
device_descriptor:
	; PID 0x0010, split per component like Logitech does:
	; bootloader_updater=0x0020, app_tx/app_rx=0x0030
	.db	18, 0x01, 0x10, 0x01, 0xFF, 0x00, 0x00, 32
	.db	0x09, 0x12, 0x10, 0x00, 0x00, 0x01, 0, 2, 0, 0x01
config_descriptor:
	.db	9, 0x02, 18, 0, 1, 1, 0, 0x80, 50
	.db	9, 0x04, 0, 0, 0, 0xFF, 0x00, 0x00, 0

;=========================================================
; String descriptors: iProduct only, no iManufacturer (no room for
; both in page 0). Same UTF-16LE encoding as app_common/usb_core.c.
string_lang:
	.db	0x04, 0x03, 0x09, 0x04			; LANGID: English (US)
string_product:
	.db	0x0A, 0x03
	.db	0x55,0x00, 0x52,0x00, 0x42,0x00, 0x6C,0x00
	; "URBl" (Unifying Radio Bootloader)
string_product_end:

;=========================================================
ram_routine:
do_flash_write:
	mov	dptr,#P_FADDRH
	movx	a,@dptr
	mov	r2,a
	mov	dptr,#P_FADDRL
	movx	a,@dptr
	mov	r3,a
	mov	dptr,#FADDRH
	mov	a,r2
	movx	@dptr,a
	mov	dptr,#FADDRL
	mov	a,r3
	movx	@dptr,a

	mov	dptr,#P_NWORDS_HI
	movx	a,@dptr
	mov	r4,a
	mov	dptr,#P_NWORDS_LO
	movx	a,@dptr
	mov	r5,a

	mov	dptr,#FCTL
	mov	a,#0x02
	movx	@dptr,a

	mov	r6,#<P_DATA
	mov	r7,#>P_DATA

wr_word_loop:
	mov	a,r4
	orl	a,r5
	jz	wr_done
	mov	dpl,r6
	mov	dph,r7
	movx	a,@dptr
	push	acc
	mov	dptr,#FWDATA
	pop	acc
	movx	@dptr,a
	inc	r6
	mov	a,r6
	jnz	wr_b2
	inc	r7
wr_b2:
	mov	dpl,r6
	mov	dph,r7
	movx	a,@dptr
	push	acc
	mov	dptr,#FWDATA
	pop	acc
	movx	@dptr,a
	inc	r6
	mov	a,r6
	jnz	wr_b3
	inc	r7
wr_b3:
	mov	dpl,r6
	mov	dph,r7
	movx	a,@dptr
	push	acc
	mov	dptr,#FWDATA
	pop	acc
	movx	@dptr,a
	inc	r6
	mov	a,r6
	jnz	wr_b4
	inc	r7
wr_b4:
	mov	dpl,r6
	mov	dph,r7
	movx	a,@dptr
	push	acc
	mov	dptr,#FWDATA
	pop	acc
	movx	@dptr,a
	inc	r6
	mov	a,r6
	jnz	wr_full_wait
	inc	r7
wr_full_wait:
	mov	dptr,#FCTL
wr_full_poll:
	movx	a,@dptr
	anl	a,#0x40
	jnz	wr_full_poll
	mov	a,r5
	jnz	wr_dec_lo
	dec	r4
wr_dec_lo:
	dec	r5
	sjmp	wr_word_loop
wr_done:
	ret

erase_entry_off	=	. - ram_routine
do_flash_erase:
	mov	dptr,#P_FADDRH
	movx	a,@dptr
	mov	dptr,#FADDRH
	movx	@dptr,a
	mov	dptr,#FADDRL
	clr	a
	movx	@dptr,a
	mov	dptr,#FCTL
	mov	a,#0x01
	movx	@dptr,a
er_wait:
	movx	a,@dptr
	anl	a,#0x80
	jnz	er_wait
	ret

ram_routine_end:
