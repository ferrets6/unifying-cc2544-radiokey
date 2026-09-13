; BOOTLOADER_UPDATER - disposable app with one job: safely rewrite the
; real bootloader (bootloader.asm, page 0), since the bootloader can't
; erase/write itself while running from there. Loaded via
; tools/flash_firmware.py like any firmware, then used with
; tools/update_bootloader.py: ERASE_STAGE1/WRITE_STAGE1_CHUNK (0x10/0x11,
; restricted to page 0 only, enforced in firmware too) + READ_CHUNK
; (0x03) for a byte-for-byte check before reset. Gets overwritten by a
; real firmware/app once the bootloader update is done - not meant to
; stay resident.
;
; Also implements the bootloader's own generic ERASE_PAGE/WRITE_CHUNK/
; FLASH_STARTED/FLASH_FINISHED (for writing other pages too, e.g. for
; testing) - same protocol, same reasoning.

	.module bootloader_updater
	.area HOME (CODE)

;=== XDATA registers, same addresses as bootloader.asm ===
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
WDCTL		=	0xC9		; direct SFR (NOT XREG/XDATA) - watchdog, see RESET_STAGE1

P_FADDRH	=	0x0200
P_FADDRL	=	0x0201
P_NWORDS_HI	=	0x0202
P_NWORDS_LO	=	0x0203
P_DATA		=	0x0210

; Explicit flash session protocol: the host declares start/end.
; FLASHING_ACTIVE: 1 between FLASH_STARTED and FLASH_FINISHED - while
;   active the main loop has no timeout, exits only via FLASH_FINISHED
;   (jumps to APP_BASE from its own handler).
; EXPECTED_LEN/WRITTEN_LEN: total length declared by FLASH_STARTED vs.
;   bytes actually accumulated by WRITE_CHUNK/WRITE_STAGE1_CHUNK -
;   compared by FLASH_FINISHED as a minimal integrity check (doesn't
;   replace the byte-for-byte READ_CHUNK verification the host still
;   does before a critical reset).
FLASHING_ACTIVE		=	0x20
EXPECTED_LEN_LO	=	0x21
EXPECTED_LEN_HI	=	0x22
WRITTEN_LEN_LO	=	0x23
WRITTEN_LEN_HI	=	0x24
; last FCTL value read right after an erase/write, exposed via
; FLASH_FINISHED's second response byte - useful to check FCTL.ABORT
; (bit 0x20, "page locked")
LAST_FCTL	=	0x25

; Stage 2 of a two-stage bootloader: stage 1 (0x0000-0x03FF) jumps here
; with a software ljmp 0x0400 - not a hardware reset, so no vector
; table/interrupt forwarding is needed (and this bootloader is polling-
; only, never enables interrupts anyway). Compiled with --code-loc
; 0x0400 so the entry point matches stage 1's jump target exactly.
;
; Never jumps to an "APP_BASE"/stage 3 - it's only a bridge to rewrite
; stage1, staying in USB listening mode until explicitly reset by the
; host after a verified stage1 write. A fixed jump address would be
; dangerous if this file gets loaded in a context where that address
; doesn't hold a valid application.
RAM_BASE_CODE	=	0x8000		; CODE view of RAM when MEMCTR.XMAP=1

;=========================================================
_start::
	mov	dptr,#0x0140
	mov	a,#0xC1
	movx	@dptr,a

	; disable the flash cache (FCTL.CM, bits 2-3): without this a write
	; can appear to succeed but not show up on READ_CHUNK, or when
	; executing freshly written code on a different page - the cache
	; serves stale data. Do this once, early, before any erase/write/
	; read on a page other than this one.
	mov	dptr,#FCTL
	movx	a,@dptr
	anl	a,#0xF3
	movx	@dptr,a

	; After the jump to stage 2, the host is still attached to stage 1's
	; USB identity until a real electrical event forces it to notice.
	; Toggling USBCTRL.PUE (D+ pull-up) alone isn't enough - the USB
	; controller's internal state (SIE) stays inconsistent after the
	; jump. Needs a real controller reset (SWRU283B 21.2: "Setting
	; USBCTRL.USB_EN to 0 resets the USB controller"), followed by the
	; same full init (PLL_EN, PLL_LOCKED wait, PUE) as after a real
	; power-on.
	;
	; USBCIF.RSTIF stays set until read: if it was already set before
	; this point (e.g. the bus reset the host does while enumerating
	; stage 1), the wait below could see it "already true" by pure
	; timing coincidence, without ever waiting for the reset caused by
	; our own toggle. So it's cleared here first, before disabling
	; USB_EN, guaranteeing the wait after only sees a genuinely new reset.
	mov	dptr,#0x6206
	movx	a,@dptr			; read (and thus clear) RSTIF

	mov	dptr,#USBADDR
	clr	a
	movx	@dptr,a			; USBADDR=0, as after a real bus reset
	mov	dptr,#USBCTRL
	clr	a
	movx	@dptr,a			; USB_EN=0: full USB controller reset
	; wide delay (3-level nesting, ~1s) before re-enabling: a
	; disconnect/reconnect too close together isn't handled reliably by
	; the host USB controller.
	mov	r5,#200
usbrst_outer:
	mov	r6,#255
	mov	r7,#0
usbrst_delay:
	djnz	r7,usbrst_delay
	djnz	r6,usbrst_delay
	djnz	r5,usbrst_outer
	; full re-init after the controller reset
	mov	dptr,#USBCTRL
	mov	a,#0x03			; USB_EN=1, PLL_EN=1
	movx	@dptr,a
usbrst_pllwait:
	mov	dptr,#USBCTRL
	movx	a,@dptr
	anl	a,#0x80			; PLL_LOCKED
	jz	usbrst_pllwait
	mov	dptr,#USBCTRL
	movx	a,@dptr
	orl	a,#0x08			; PUE=1 (reconnect, host sees it as new)
	movx	@dptr,a

	; Wait for the real bus reset driven by the HOST (USBCIF.RSTIF,
	; XDATA 0x6206 bit2) - separate and asynchronous from our own toggle
	; above, driven by the host noticing the device (SE0 signaling), not
	; something we control. SWRU283B 21.9: "Firmware should... wait for
	; a new enumeration phase when USB reset is detected".
	mov	dptr,#0x6206
rstif_wait:
	movx	a,@dptr			; self-clears on read (R,H0)
	anl	a,#0x04			; RSTIF
	jz	rstif_wait

	; --- copy ram_routine (CODE) -> xdata 0x0000 ---
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

	; Initial window: gives the host time to send FLASH_STARTED. Once
	; received, the loop below has no timeout at all (exits only via
	; FLASH_FINISHED) - explicit protocol instead of an implicit
	; timeout, so a write session in progress can never be interrupted
	; mid-way.
	;
	; ~30-35s window (r2=6) to give enough margin when this file gets
	; loaded not by our bootloader but via the real Logitech DFU
	; mechanism (where there's no real "stage 3" at APP_BASE - see below).
	mov	FLASHING_ACTIVE,#0
	mov	r2,#6
window_repeat:
	mov	r1,#200
window_outer:
	mov	r0,#0
window_inner:
	lcall	usb_poll
	mov	a,FLASHING_ACTIVE
	jnz	window_inner		; flash session declared active: no timeout,
					; exits only via FLASH_FINISHED
	djnz	r0,window_inner
	djnz	r1,window_outer
	djnz	r2,window_repeat

	mov	dptr,#0x0140
	mov	a,#0xC0
	movx	@dptr,a

	; This bootloader_updater only exists to bridge to a stage1 write,
	; not to launch an app at APP_BASE - the real workflow
	; (tools/update_bootloader.py) never calls FLASH_FINISHED and never
	; hits this timeout. A fixed jump to APP_BASE=0x1000 would be
	; dangerous anyway if this file is loaded as an "app" via the real
	; Logitech DFU mechanism instead of our own bootloader - 0x1000
	; would still hold the old Logitech firmware, an unrelated jump
	; target. Restart the window instead of jumping anywhere.
	ljmp	window_repeat

;=========================================================
; usb_poll: non-blocking initial SETUP dispatch; WRITE_CHUNK's data
; phase is instead handled blocking, inside handle_write_chunk.
;=========================================================
usb_poll:
	mov	dptr,#USBINDEX
	clr	a
	movx	@dptr,a
	mov	dptr,#USBCS0
	movx	a,@dptr
	anl	a,#0x01			; OUTPKT_RDY
	jnz	usb_poll_has_pkt
	ljmp	poll_ret		; long jump: poll_ret is out of jz range
usb_poll_has_pkt:

	push	dpl
	push	dph
	push	acc
	mov	dptr,#0x0141
	mov	a,#0xD0
	movx	@dptr,a
	pop	acc
	pop	dph
	pop	dpl

	; read the 8 SETUP bytes from USBF0 - keep bmRequestType too:
	; dropping it would confuse a STANDARD request's bRequest=1/2 (e.g.
	; CLEAR_FEATURE=1) with our vendor commands using the same numeric
	; values in a different bmRequestType namespace.
	mov	dptr,#USBF0
	movx	a,@dptr
	mov	r1,a			; bmRequestType
	movx	a,@dptr
	mov	r2,a			; bRequest
	movx	a,@dptr
	mov	r3,a			; wValue lo
	movx	a,@dptr
	mov	r4,a			; wValue hi
	movx	a,@dptr			; wIndex lo - discarded
	movx	a,@dptr			; wIndex hi - discarded
	movx	a,@dptr
	mov	r5,a			; wLength lo
	movx	a,@dptr
	mov	r6,a			; wLength hi

	mov	dptr,#0x0142
	mov	a,r1
	movx	@dptr,a
	mov	dptr,#0x0143
	mov	a,r2
	movx	@dptr,a

	; dispatch by TYPE before bRequest: (bmRequestType & 0x60) == 0x40
	; (vendor), else standard
	mov	a,r1
	anl	a,#0x60
	xrl	a,#0x40
	jnz	dispatch_standard

	; --- VENDOR type: ERASE_PAGE/WRITE_CHUNK/READ_CHUNK, else stall ---
	mov	a,r2
	cjne	a,#0x01,chk_write
	ljmp	handle_erase_page
chk_write:
	cjne	a,#0x02,chk_read
	ljmp	handle_write_chunk
chk_read:
	cjne	a,#0x03,chk_flash_started
	ljmp	handle_read_chunk
chk_flash_started:
	cjne	a,#0x04,chk_flash_finished
	ljmp	handle_flash_started
chk_flash_finished:
	cjne	a,#0x05,chk_get_last_fctl
	ljmp	handle_flash_finished
chk_get_last_fctl:
	cjne	a,#0x06,chk_erase_stage1
	ljmp	handle_get_last_fctl

	; Commands restricted to page 0 only (0x0000-0x03FF, where stage 1
	; lives) - page/address are checked here in firmware, not just
	; trusted from the host script, so a buggy host can never target the
	; wrong page. Stage 2 lives in page 1 (0x0400+): writing here is not
	; self-overwrite, reuses handle_erase_page/handle_write_chunk as-is
	; with a forced/verified address instead of one taken from the host.
chk_erase_stage1:
	cjne	a,#0x10,chk_write_stage1
	mov	a,r3
	jnz	do_stall		; ERASE_STAGE1 accepts page 0 only
	ljmp	handle_erase_page
chk_write_stage1:
	cjne	a,#0x11,chk_reset_stage1
	mov	a,r4
	clr	c
	subb	a,#4
	jnc	do_stall		; address (high byte) >= 4: outside page 0
	cjne	a,#0xFF,ws1_safe	; a=0xFF only if r4 was exactly 3 (wrap after subb)
	mov	a,r3
	add	a,r5
	; A plain "jc do_stall" here would also reject the valid case where
	; the chunk ends exactly at page 0's last byte (r3+r5=256 exactly ->
	; 8-bit overflow wraps to 0, a valid boundary, not overrun). Must
	; distinguish a real overflow (wrapped result != 0, truly spills
	; into page 1) from an exact boundary (wrapped result == 0, valid).
	jnc	ws1_safe		; no overflow (sum <=255): always inside page 0
	jnz	do_stall		; real overflow: would exceed 0x03FF
					; overflow with wrap==0 (r3+r5=256 exactly): valid
					; boundary, falls through to ws1_safe
ws1_safe:
	ljmp	handle_write_chunk

	; RESET_STAGE1 (0x12): the only way to restart the chip from USB
	; after "VERIFICA OK", no debug clip needed. Same technique as
	; SOFT_RESET in app_common/usb_core.c: writes WDCTL directly (SFR
	; access, not movx). No parameters, no data.
chk_reset_stage1:
	cjne	a,#0x12,do_stall
	ljmp	handle_reset_stage1

	; --- STANDARD type: GET_DESCRIPTOR/SET_ADDRESS/SET_CONFIGURATION ---
dispatch_standard:
	mov	a,r2
	cjne	a,#0x06,chk_setaddr
	ljmp	handle_get_descriptor
chk_setaddr:
	cjne	a,#0x05,chk_setconf
	; SET_ADDRESS: ack, then USBADDR = wValue&0x7F
	mov	dptr,#USBCS0
	mov	a,#0x48			; CLR_OUTPKT_RDY|DATA_END
	movx	@dptr,a
	mov	a,r3
	anl	a,#0x7F
	mov	dptr,#USBADDR
	movx	@dptr,a
	sjmp	poll_ret
chk_setconf:
	cjne	a,#0x09,do_stall
	; SET_CONFIGURATION: ack, no data
	mov	dptr,#USBCS0
	mov	a,#0x48
	movx	@dptr,a
	sjmp	poll_ret
do_stall:
	mov	dptr,#USBCS0
	mov	a,#0x40			; CLR_OUTPKT_RDY
	movx	@dptr,a
	mov	a,#0x20			; SEND_STALL
	movx	@dptr,a
poll_ret:
	ret

;=========================================================
; ERASE_PAGE: R3 = page number
;=========================================================
handle_erase_page:
	mov	dptr,#USBCS0
	mov	a,#0x48			; ack (no data)
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

	mov	dptr,#FCTL
	movx	a,@dptr
	mov	LAST_FCTL,a

	ljmp	poll_ret

;=========================================================
; WRITE_CHUNK: R3:R4 = target byte address, R5:R6 = wLength (bytes).
; Receives OUT data blocking (loop inline), then writes.
;=========================================================
handle_write_chunk:
	; ack end of SETUP phase, enter OUT data phase (no DATA_END yet)
	mov	dptr,#USBCS0
	mov	a,#0x40
	movx	@dptr,a

	mov	r0,#<P_DATA
	mov	r1,#>P_DATA		; r0:r1 = current xdata write pointer
	mov	a,r5
	mov	r7,a			; remaining byte count, low
					; NOTE: assumes wLength < 256
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
	mov	r2,a			; bytes in this packet
	mov	dptr,#USBF0
recv_byte:
	mov	a,r2
	jz	recv_pkt_done
	movx	a,@dptr			; read from EP0 FIFO
	push	acc
	mov	dpl,r0
	mov	dph,r1
	pop	acc
	movx	@dptr,a			; write to P_DATA buffer
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
	; all received: final ack
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
	; WRITTEN_LEN += wLength (r5:r6). Internal RAM (mov, not movx):
	; these addresses (0x21-0x25) coincide in XDATA with the
	; ram_routine copy (see copyloop in _start) - an movx here would
	; corrupt the flash-write routine before it runs via
	; lcall RAM_BASE_CODE.
	mov	a,WRITTEN_LEN_LO
	add	a,r5
	mov	WRITTEN_LEN_LO,a
	mov	a,WRITTEN_LEN_HI
	addc	a,r6
	mov	WRITTEN_LEN_HI,a

	; wordaddr = wValue>>2 (r3:r4 >> 2), nwords = wLength>>2 (r5:r6 >> 2)
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
	; r4:r3 = wordaddr (hi:lo)
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

	mov	dptr,#FCTL
	movx	a,@dptr
	mov	LAST_FCTL,a

	ljmp	poll_ret

;=========================================================
; READ_CHUNK: R3:R4 = address (wValue lo:hi), R5:R6 = length in bytes
; (wLength lo:hi, up to 252, same limit as WRITE_CHUNK). Reads from CODE
; (real flash via normal fetch, MEMCTR.XMAP never active here) and sends
; it back on EP0 IN one 32-byte packet (bMaxPacketSize0) at a time - the
; only way left to verify a write byte-for-byte without a debug interface.
;=========================================================
handle_read_chunk:
	mov	dptr,#USBCS0
	mov	a,#0x40			; CLR_OUTPKT_RDY (ack SETUP, no OUT data)
	movx	@dptr,a

rc_loop:
	; r7 = min(32, remaining) - remaining is r5:r6 (16 bit)
	mov	a,r6
	jnz	rc_full32		; hi byte nonzero: definitely more than 32 left
	mov	a,r5
	clr	c
	subb	a,#33
	jnc	rc_full32		; r5>=33: more than 32 left, full packet (not last)
	mov	a,r5			; last packet: 0-32 bytes left
	mov	r7,a
	sjmp	rc_send
rc_full32:
	mov	r7,#32
rc_send:
	mov	dptr,#USBF0
rc_byte:
	mov	a,r7
	jz	rc_pktdone
	mov	dpl,r3
	mov	dph,r4
	clr	a
	movc	a,@a+dptr
	push	acc
	mov	dptr,#USBF0
	pop	acc
	movx	@dptr,a
	inc	r3
	mov	a,r3
	jnz	rc_nc
	inc	r4
rc_nc:
	dec	r7
	mov	a,r5			; also decrement the total remaining r5:r6
	jnz	rc_dec5
	dec	r6
rc_dec5:
	dec	r5
	sjmp	rc_byte
rc_pktdone:
	mov	a,r5			; last packet if the remaining total is now 0
	orl	a,r6
	jnz	rc_notlast
	mov	dptr,#USBCS0
	mov	a,#0x0A			; INPKT_RDY|DATA_END
	movx	@dptr,a
	ljmp	poll_ret
rc_notlast:
	mov	dptr,#USBCS0
	mov	a,#0x02			; INPKT_RDY (not the last packet)
	movx	@dptr,a
rc_wait:				; wait for the host to pick it up before the next one
	mov	dptr,#USBCS0
	movx	a,@dptr
	anl	a,#0x02
	jnz	rc_wait
	ljmp	rc_loop

;=========================================================
; FLASH_STARTED (bRequest 0x04, OUT no data): declares the start of a
; write session. wValue (r3:r4) = total bytes the host intends to write
; (sum of all WRITE_CHUNK/WRITE_STAGE1_CHUNK to follow). Disables the
; window's timeout until FLASH_FINISHED.
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
; against EXPECTED_LEN, replies 0x00 (OK) or 0x01 (mismatch), then jumps
; straight to APP_BASE - explicitly commanded by the host, no guessing.
; This is only a minimal length check, doesn't replace the byte-for-byte
; READ_CHUNK verification the host still does before a critical reset.
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
	mov	a,#0x40			; CLR_OUTPKT_RDY (no OUT phase)
	movx	@dptr,a
	mov	dptr,#USBF0
	mov	a,r6
	movx	@dptr,a			; byte 0: status (0x00 OK / 0x01 mismatch)
	mov	a,LAST_FCTL
	movx	@dptr,a			; byte 1: last FCTL value
	mov	dptr,#USBCS0
	mov	a,#0x0A			; INPKT_RDY|DATA_END
	movx	@dptr,a
ff_txwait:
	; wait for hardware confirmation the SIE actually sent the status
	; packet (INPKT_RDY self-clears once ACKed by the host) - only then
	; is it safe to do a destructive USB controller reset (the next
	; stage does one in its own init).
	movx	a,@dptr
	anl	a,#0x02
	jnz	ff_txwait
	mov	FLASHING_ACTIVE,#0
	; FLASH_FINISHED is never used in the real stage1-update workflow
	; (tools/update_bootloader.py never calls it), but if it were sent
	; by mistake, go back to listening instead of jumping to an
	; APP_BASE that might not hold anything valid.
	ljmp	window_repeat

;=========================================================
; RESET_STAGE1 (bRequest 0x12, OUT no data): the only way to restart the
; chip from USB after a verified write, no debug clip needed. Same
; technique as SOFT_RESET in app_common/usb_core.c: writes WDCTL=0x0B
; (MODE=10 watchdog, INT=11 ~1.9ms) directly. Ack before arming the
; watchdog, same order as usb_core.c, so the host sees the USB
; transaction complete cleanly before the chip disappears from the bus.
;=========================================================
handle_reset_stage1:
	mov	dptr,#USBCS0
	mov	a,#0x48			; CLR_OUTPKT_RDY|DATA_END - ack (no data)
	movx	@dptr,a
	mov	WDCTL,#0x0B		; direct SFR access, not movx
	ljmp	poll_ret		; never really returns: hw reset within ~1.9ms

;=========================================================
; GET_LAST_FCTL (bRequest 0x06, IN 1 byte): returns LAST_FCTL without
; jumping away, so FCTL.ABORT can be checked after an erase/write
; without losing control of the chip (unlike FLASH_FINISHED, which
; always jumps).
;=========================================================
handle_get_last_fctl:
	mov	dptr,#USBCS0
	mov	a,#0x40
	movx	@dptr,a
	mov	dptr,#USBF0
	mov	a,LAST_FCTL
	movx	@dptr,a
	mov	dptr,#USBCS0
	mov	a,#0x0A
	movx	@dptr,a
	ljmp	poll_ret

;=========================================================
; GET_DESCRIPTOR (device/config only, 18 bytes each, fits in one 32-byte
; EP0 packet). R4 = wValue hi (descriptor type), R5:R6 = wLength.
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
	cjne	a,#0x02,gd_stall
	mov	dptr,#config_descriptor
	sjmp	gd_send
gd_stall:
	mov	dptr,#USBCS0
	mov	a,#0x20
	movx	@dptr,a
	ljmp	poll_ret

gd_send:
	; r2:r3 = CODE pointer to the chosen descriptor
	mov	r2,dpl
	mov	r3,dph
	; count to send = min(18, wLength) - if wLength hi!=0 assume >=18
	mov	a,r6
	jnz	gd_len18
	mov	a,r5
	clr	c
	subb	a,#18
	jc	gd_lenW			; wLength < 18: use wLength (r5)
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
	mov	a,#0x0A			; INPKT_RDY|DATA_END
	movx	@dptr,a
	ljmp	poll_ret

;=========================================================
; descriptors (constant data, CODE)
;=========================================================
device_descriptor:
	; PID 0x0020, split per component: bootloader=0x0010,
	; bootloader_updater(here)=0x0020, app_tx/app_rx=0x0030
	.db	18, 0x01, 0x10, 0x01, 0xFF, 0x00, 0x00, 32
	.db	0x09, 0x12, 0x20, 0x00, 0x00, 0x01, 0, 0, 0, 0x01
config_descriptor:
	.db	9, 0x02, 18, 0, 1, 1, 0, 0x80, 50
	.db	9, 0x04, 0, 0, 0, 0xFF, 0x00, 0x00, 0

;=========================================================
; ram_routine: copied to xdata 0x0000, executed from there via CODE
; 0x8000 (MEMCTR.XMAP=1). Two entry points:
;   offset 0 (RAM_BASE_CODE+0)                = do_flash_write
;   offset erase_entry_off (RAM_BASE_CODE+off) = do_flash_erase
;=========================================================
ram_routine:
do_flash_write:
	; FADDRH = P_FADDRH ; FADDRL = P_FADDRL
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

	; nwords = P_NWORDS_HI:P_NWORDS_LO -> r4:r5
	mov	dptr,#P_NWORDS_HI
	movx	a,@dptr
	mov	r4,a
	mov	dptr,#P_NWORDS_LO
	movx	a,@dptr
	mov	r5,a

	; FCTL = 0x02 (WRITE=1)
	mov	dptr,#FCTL
	mov	a,#0x02
	movx	@dptr,a

	; source data pointer: r6:r7 = P_DATA
	mov	r6,#<P_DATA
	mov	r7,#>P_DATA

wr_word_loop:
	mov	a,r4
	orl	a,r5
	jz	wr_done
	; write 4 bytes from (r6:r7) to FWDATA
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
	anl	a,#0x40			; FULL
	jnz	wr_full_poll
	; nwords-- (r4:r5, 16bit)
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
	mov	a,#0x01			; ERASE=1
	movx	@dptr,a
er_wait:
	movx	a,@dptr
	anl	a,#0x80			; BUSY
	jnz	er_wait
	ret

ram_routine_end:
