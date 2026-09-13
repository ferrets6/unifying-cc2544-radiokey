#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Minimal but fairly complete 8051 (MCS-51) disassembler, written from scratch
because no ready-made 8051 disassembler tool was available on this machine
(no d52, no sdcc/as8051, no pip package, no local Ghidra 8051 processor).

Does recursive-descent disassembly (follows JMP/CALL/conditional branches)
starting from a set of entry points, so we don't blindly linear-sweep over
data embedded in the code segment (e.g. the vector table at 0x0400).
"""
import sys

def load_ihex(path):
    mem = bytearray(65536)
    present = bytearray(65536)  # 1 if byte was defined by the hex file
    base = 0
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith(':'):
                continue
            data = bytes.fromhex(line[1:])
            count = data[0]
            addr = (data[1] << 8) | data[2]
            rtype = data[3]
            payload = data[4:4+count]
            if rtype == 0x00:  # data record
                a = base + addr
                for i, b in enumerate(payload):
                    if a + i < 65536:
                        mem[a+i] = b
                        present[a+i] = 1
            elif rtype == 0x01:  # EOF
                break
            elif rtype == 0x02:  # extended segment address
                base = ((payload[0] << 8) | payload[1]) << 4
            elif rtype == 0x04:  # extended linear address
                base = ((payload[0] << 8) | payload[1]) << 16
            elif rtype == 0x05:  # start linear address - ignore
                pass
            else:
                pass
    return mem, present

# Register names R0-R7 handled inline.

# Opcode table: opcode -> (mnemonic, operand-kind, length)
# operand kinds:
#  N      : no operand
#  A11    : addr11 (AJMP/ACALL) len=2
#  A16    : addr16 (LJMP/LCALL) len=3
#  REL    : rel8 (unconditional/SJMP) len=2
#  BREL   : bit, rel  len=3 (JB/JNB/JBC)
#  CREL   : rel (JC/JNC/JZ/JNZ) len=2
#  IMM    : #data len=2 (A,#data or Rn,#data or @Ri,#data)
#  DIR    : direct len=2
#  DIRA   : direct (A,direct or direct,A) len=2
#  DIRIMM : direct,#data len=3
#  DIRREL : direct,rel len=3 (DJNZ direct,rel)
#  RNREL  : Rn,rel len=2 (DJNZ Rn,rel)
#  IMMREL : #data,rel len=3 (CJNE A,#data,rel)
#  DIRRELC: direct,rel len=3 (CJNE A,direct,rel)
#  RIMMREL: (Rn/@Ri),#data,rel len=3 (CJNE Rn/@Ri,#data,rel)
#  BIT    : bit len=2 (SETB/CLR/CPL bit, MOV C,bit / MOV bit,C, ANL/ORL C,bit)
#  DIRDIR : direct,direct len=3 (MOV direct,direct; encoded src,dest in bytes)
#  DATA16 : #data16 len=3 (MOV DPTR,#data16)

OPS = {}

def add(op, mnem, kind, length):
    OPS[op] = (mnem, kind, length)

# Row 0x00
add(0x00, "NOP", "N", 1)
add(0x02, "LJMP", "A16", 3)
add(0x03, "RR A", "N", 1)
add(0x04, "INC A", "N", 1)
add(0x05, "INC ", "DIR", 2)
for i, r in enumerate(range(0x06, 0x08)):
    add(r, f"INC @R{i}", "N", 1)
for i in range(8):
    add(0x08+i, f"INC R{i}", "N", 1)

# Row 0x10
add(0x10, "JBC", "BREL", 3)
add(0x12, "LCALL", "A16", 3)
add(0x13, "RRC A", "N", 1)
add(0x14, "DEC A", "N", 1)
add(0x15, "DEC ", "DIR", 2)
add(0x16, "DEC @R0", "N", 1)
add(0x17, "DEC @R1", "N", 1)
for i in range(8):
    add(0x18+i, f"DEC R{i}", "N", 1)

# Row 0x20
add(0x20, "JB", "BREL", 3)
add(0x22, "RET", "N", 1)
add(0x23, "RL A", "N", 1)
add(0x24, "ADD A,#0x%02X", "IMM", 2)
add(0x25, "ADD A,", "DIR", 2)
add(0x26, "ADD A,@R0", "N", 1)
add(0x27, "ADD A,@R1", "N", 1)
for i in range(8):
    add(0x28+i, f"ADD A,R{i}", "N", 1)

# Row 0x30
add(0x30, "JNB", "BREL", 3)
add(0x32, "RETI", "N", 1)
add(0x33, "RLC A", "N", 1)
add(0x34, "ADDC A,#0x%02X", "IMM", 2)
add(0x35, "ADDC A,", "DIR", 2)
add(0x36, "ADDC A,@R0", "N", 1)
add(0x37, "ADDC A,@R1", "N", 1)
for i in range(8):
    add(0x38+i, f"ADDC A,R{i}", "N", 1)

# Row 0x40
add(0x40, "JC", "CREL", 2)
add(0x42, "ORL ", "DIRA_DA", 2)   # ORL direct,A
add(0x43, "ORL ", "DIRIMM", 3)    # ORL direct,#data
add(0x44, "ORL A,#0x%02X", "IMM", 2)
add(0x45, "ORL A,", "DIR", 2)
add(0x46, "ORL A,@R0", "N", 1)
add(0x47, "ORL A,@R1", "N", 1)
for i in range(8):
    add(0x48+i, f"ORL A,R{i}", "N", 1)

# Row 0x50
add(0x50, "JNC", "CREL", 2)
add(0x52, "ANL ", "DIRA_DA", 2)
add(0x53, "ANL ", "DIRIMM", 3)
add(0x54, "ANL A,#0x%02X", "IMM", 2)
add(0x55, "ANL A,", "DIR", 2)
add(0x56, "ANL A,@R0", "N", 1)
add(0x57, "ANL A,@R1", "N", 1)
for i in range(8):
    add(0x58+i, f"ANL A,R{i}", "N", 1)

# Row 0x60
add(0x60, "JZ", "CREL", 2)
add(0x62, "XRL ", "DIRA_DA", 2)
add(0x63, "XRL ", "DIRIMM", 3)
add(0x64, "XRL A,#0x%02X", "IMM", 2)
add(0x65, "XRL A,", "DIR", 2)
add(0x66, "XRL A,@R0", "N", 1)
add(0x67, "XRL A,@R1", "N", 1)
for i in range(8):
    add(0x68+i, f"XRL A,R{i}", "N", 1)

# Row 0x70
add(0x70, "JNZ", "CREL", 2)
add(0x72, "ORL C,", "BIT", 2)
add(0x73, "JMP @A+DPTR", "N", 1)
add(0x74, "MOV A,#0x%02X", "IMM", 2)
add(0x75, "MOV ", "DIRIMM", 3)
add(0x76, "MOV @R0,#0x%02X", "IMM", 2)
add(0x77, "MOV @R1,#0x%02X", "IMM", 2)
for i in range(8):
    add(0x78+i, f"MOV R{i},#0x%02X", "IMM", 2)

# Row 0x80
add(0x80, "SJMP", "REL", 2)
add(0x82, "ANL C,", "BIT", 2)
add(0x83, "MOVC A,@A+PC", "N", 1)
add(0x84, "DIV AB", "N", 1)
add(0x85, "MOV ", "DIRDIR", 3)
add(0x86, "MOV ,@R0", "DIR_LEFT", 2)
add(0x87, "MOV ,@R1", "DIR_LEFT", 2)
for i in range(8):
    add(0x88+i, f"MOV ,R{i}", "DIR_LEFT", 2)

# Row 0x90
add(0x90, "MOV DPTR,#0x%04X", "DATA16", 3)
add(0x92, "MOV ", "BIT_C", 2)   # MOV bit,C
add(0x93, "MOVC A,@A+DPTR", "N", 1)
add(0x94, "SUBB A,#0x%02X", "IMM", 2)
add(0x95, "SUBB A,", "DIR", 2)
add(0x96, "SUBB A,@R0", "N", 1)
add(0x97, "SUBB A,@R1", "N", 1)
for i in range(8):
    add(0x98+i, f"SUBB A,R{i}", "N", 1)

# Row 0xA0
add(0xA0, "ORL C,/", "BIT", 2)
add(0xA2, "MOV C,", "BIT", 2)
add(0xA3, "INC DPTR", "N", 1)
add(0xA4, "MUL AB", "N", 1)
# 0xA5 reserved/undefined
add(0xA6, "MOV @R0,", "DIR", 2)
add(0xA7, "MOV @R1,", "DIR", 2)
for i in range(8):
    add(0xA8+i, f"MOV R{i},", "DIR", 2)

# Row 0xB0
add(0xB0, "ANL C,/", "BIT", 2)
add(0xB2, "CPL ", "BIT", 2)
add(0xB3, "CPL C", "N", 1)
add(0xB4, "CJNE A,#0x%02X,", "IMMREL", 3)
add(0xB5, "CJNE A,", "DIRRELC", 3)
add(0xB6, "CJNE @R0,#0x%02X,", "IMMREL", 3)
add(0xB7, "CJNE @R1,#0x%02X,", "IMMREL", 3)
for i in range(8):
    add(0xB8+i, f"CJNE R{i},#0x%02X,", "IMMREL", 3)

# Row 0xC0
add(0xC0, "PUSH ", "DIR", 2)
add(0xC2, "CLR ", "BIT", 2)
add(0xC3, "CLR C", "N", 1)
add(0xC4, "SWAP A", "N", 1)
add(0xC5, "XCH A,", "DIR", 2)
add(0xC6, "XCH A,@R0", "N", 1)
add(0xC7, "XCH A,@R1", "N", 1)
for i in range(8):
    add(0xC8+i, f"XCH A,R{i}", "N", 1)

# Row 0xD0
add(0xD0, "POP ", "DIR", 2)
add(0xD2, "SETB ", "BIT", 2)
add(0xD3, "SETB C", "N", 1)
add(0xD4, "DA A", "N", 1)
add(0xD5, "DJNZ ", "DIRREL", 3)
add(0xD6, "XCHD A,@R0", "N", 1)
add(0xD7, "XCHD A,@R1", "N", 1)
for i in range(8):
    add(0xD8+i, f"DJNZ R{i},", "RNREL", 2)

# Row 0xE0
add(0xE0, "MOVX A,@DPTR", "N", 1)
add(0xE2, "MOVX A,@R0", "N", 1)
add(0xE3, "MOVX A,@R1", "N", 1)
add(0xE4, "CLR A", "N", 1)
add(0xE5, "MOV A,", "DIR", 2)
add(0xE6, "MOV A,@R0", "N", 1)
add(0xE7, "MOV A,@R1", "N", 1)
for i in range(8):
    add(0xE8+i, f"MOV A,R{i}", "N", 1)

# Row 0xF0
add(0xF0, "MOVX @DPTR,A", "N", 1)
add(0xF2, "MOVX @R0,A", "N", 1)
add(0xF3, "MOVX @R1,A", "N", 1)
add(0xF4, "CPL A", "N", 1)
add(0xF5, "MOV ,A", "DIR_LEFT_A", 2)
add(0xF6, "MOV @R0,A", "N", 1)
add(0xF7, "MOV @R1,A", "N", 1)
for i in range(8):
    add(0xF8+i, f"MOV R{i},A", "N", 1)

# AJMP/ACALL: opcodes x1 where low nibble pattern is a1 or a3 (0x01,0x21,0x41,...,0xE1)
# and x1 = 0x11,0x31,...(ACALL). Pattern: opcode & 0x1F == 0x01 -> AJMP; == 0x11 -> ACALL
for page in range(8):
    ajmp_op = (page << 5) | 0x01
    acall_op = (page << 5) | 0x11
    add(ajmp_op, "AJMP", "A11", 2)
    add(acall_op, "ACALL", "A11", 2)

def s8(b):
    return b - 256 if b >= 128 else b

def sfr_name(v, sfr_names):
    return sfr_names.get(v, f"0x{v:02X}")

def bit_name(v, bit_names):
    return bit_names.get(v, f"0x{v:02X}")

def disasm_one(mem, addr, sfr_names, bit_names):
    op = mem[addr]
    if op not in OPS:
        return (f"DB 0x{op:02X}  ; unknown/reserved opcode", 1, [])
    mnem, kind, length = OPS[op]
    targets = []
    if kind == "N":
        text = mnem
    elif kind == "A11":
        b2 = mem[addr+1]
        page = (op >> 5) & 0x07
        target = ((addr + length) & 0xF800) | (page << 8) | b2
        text = f"{mnem} 0x{target:04X}"
        targets.append(target)
    elif kind == "A16":
        target = (mem[addr+1] << 8) | mem[addr+2]
        text = f"{mnem} 0x{target:04X}"
        targets.append(target)
    elif kind == "REL":
        rel = s8(mem[addr+1])
        target = (addr + length + rel) & 0xFFFF
        text = f"{mnem} 0x{target:04X}"
        targets.append(target)
    elif kind == "CREL":
        rel = s8(mem[addr+1])
        target = (addr + length + rel) & 0xFFFF
        text = f"{mnem} 0x{target:04X}"
        targets.append(target)
        targets.append(addr+length)  # fallthrough
    elif kind == "BREL":
        bitv = mem[addr+1]
        rel = s8(mem[addr+2])
        target = (addr + length + rel) & 0xFFFF
        text = f"{mnem} {bit_name(bitv, bit_names)},0x{target:04X}"
        targets.append(target)
        targets.append(addr+length)
    elif kind == "IMM":
        imm = mem[addr+1]
        text = mnem % imm
    elif kind == "DIR":
        d = mem[addr+1]
        text = mnem + sfr_name(d, sfr_names)
    elif kind == "DIRA_DA":
        d = mem[addr+1]
        text = mnem + f"{sfr_name(d, sfr_names)},A"
    elif kind == "DIRIMM":
        d = mem[addr+1]; imm = mem[addr+2]
        text = mnem + f"{sfr_name(d, sfr_names)},#0x{imm:02X}"
    elif kind == "DIRREL":
        d = mem[addr+1]; rel = s8(mem[addr+2])
        target = (addr+length+rel) & 0xFFFF
        text = mnem + f"{sfr_name(d, sfr_names)},0x{target:04X}"
        targets.append(target); targets.append(addr+length)
    elif kind == "RNREL":
        rel = s8(mem[addr+1])
        target = (addr+length+rel) & 0xFFFF
        text = mnem + f"0x{target:04X}"
        targets.append(target); targets.append(addr+length)
    elif kind == "IMMREL":
        imm = mem[addr+1]; rel = s8(mem[addr+2])
        target = (addr+length+rel) & 0xFFFF
        text = (mnem % imm) + f"0x{target:04X}"
        targets.append(target); targets.append(addr+length)
    elif kind == "DIRRELC":
        d = mem[addr+1]; rel = s8(mem[addr+2])
        target = (addr+length+rel) & 0xFFFF
        text = mnem + f"{sfr_name(d, sfr_names)},0x{target:04X}"
        targets.append(target); targets.append(addr+length)
    elif kind == "BIT":
        b = mem[addr+1]
        text = mnem + bit_name(b, bit_names)
    elif kind == "BIT_C":
        b = mem[addr+1]
        text = f"MOV {bit_name(b, bit_names)},C"
    elif kind == "DIRDIR":
        src = mem[addr+1]; dst = mem[addr+2]
        text = f"MOV {sfr_name(dst, sfr_names)},{sfr_name(src, sfr_names)}"
    elif kind == "DIR_LEFT":
        d = mem[addr+1]
        # mnem like "MOV ,@R0" or "MOV ,R3" -> insert direct after MOV
        text = mnem.replace("MOV ,", f"MOV {sfr_name(d, sfr_names)},")
    elif kind == "DIR_LEFT_A":
        d = mem[addr+1]
        text = f"MOV {sfr_name(d, sfr_names)},A"
    elif kind == "DATA16":
        val = (mem[addr+1] << 8) | mem[addr+2]
        text = mnem % val
    else:
        text = f"??? kind={kind}"
    raw = " ".join(f"{mem[addr+i]:02X}" for i in range(length))
    return (text, length, targets, raw, op)

def recursive_disasm(mem, present, entries, sfr_names, bit_names, max_addr=0x10000):
    visited = {}
    stack = list(entries)
    calls_from = {}
    while stack:
        addr = stack.pop()
        if addr in visited or addr >= max_addr:
            continue
        if not present[addr]:
            continue
        try:
            res = disasm_one(mem, addr, sfr_names, bit_names)
        except IndexError:
            continue
        text, length, targets = res[0], res[1], res[2]
        raw = res[3] if len(res) > 3 else ""
        op = res[4] if len(res) > 4 else mem[addr]
        visited[addr] = (text, length, raw, op)
        is_terminal = text.startswith("LJMP") or text.startswith("AJMP") or text.startswith("SJMP") or text == "RET" or text == "RETI" or text.startswith("JMP @A+DPTR")
        for t in targets:
            stack.append(t)
        if not is_terminal:
            stack.append(addr + length)
        # also follow LCALL/ACALL targets already in `targets` (handled generically since A11/A16 add target)
    return visited

XDATA_NAMES = {
    0x6000: "PRF_CHAN", 0x6001: "PRF_TASK_CONF", 0x6002: "PRF_FIFO_CONF",
    0x6003: "PRF_PKT_CONF", 0x6004: "PRF_CRC_LEN",
    0x6180: "FRMCTRL0", 0x6181: "FRMCTRL1", 0x6184: "FREQCTRL",
    0x6190: "MDMCTRL0", 0x6191: "MDMCTRL1", 0x6192: "MDMCTRL2",
    0x6195: "SW0", 0x6196: "SW1", 0x6197: "SW2", 0x6198: "SW3",
    0x620F: "USBCTRL", 0x624B: "TR0",
    0x61E0: "BSP_STATUS", 0x61E1: "BSP_CONFIG",
}
for _a in range(0x6018, 0x6024):
    XDATA_NAMES[_a] = f"PRF_ADDR_ENTRY0+{_a-0x6018}"

def format_listing(visited, start=None, end=None, annotate_xdata=True):
    addrs = sorted(visited.keys())
    lines = []
    dptr = None  # best-effort straight-line DPTR tracker, for annotation only
    for a in addrs:
        if start is not None and a < start:
            continue
        if end is not None and a > end:
            continue
        text, length, raw, op = visited[a]
        comment = ""
        if annotate_xdata:
            if text.startswith("MOV DPTR,#0x"):
                try:
                    dptr = int(text.split("#0x")[1], 16)
                except ValueError:
                    dptr = None
            elif text == "INC DPTR" and dptr is not None:
                dptr = (dptr + 1) & 0xFFFF
            elif text in ("MOVX @DPTR,A", "MOVX A,@DPTR") and dptr is not None:
                name = XDATA_NAMES.get(dptr)
                if name:
                    comment = f"  ; XDATA 0x{dptr:04X} = {name}"
                else:
                    comment = f"  ; XDATA 0x{dptr:04X}"
        lines.append(f"{a:04X}:  {raw:<9s} {text}{comment}")
    return "\n".join(lines)

if __name__ == "__main__":
    path = sys.argv[1]
    mem, present = load_ihex(path)
    # Minimal SFR name table (8051 standard + CC2544-specific ones we care about)
    sfr_names = {
        0x81: "SP", 0x82: "DPL", 0x83: "DPH", 0x87: "PCON",
        0x88: "TCON", 0x89: "TMOD", 0x8A: "TL0", 0x8B: "TL1",
        0x8C: "TH0", 0x8D: "TH1", 0x90: "P1",
        0x98: "SCON", 0x99: "SBUF",
        0xA0: "P2", 0xA8: "IEN0",
        0xB0: "P3", 0xB8: "IEN1",
        0xC0: "IRCON", 0xC6: "CLKCONCMD", 0xC7: "PMUX",
        0xC8: "T2CT", 0xD0: "PSW", 0xD9: "RFD", 0xE0: "ACC",
        0xE1: "RFST", 0xF0: "B", 0x9E: "CLKCONSTA",
        0xB3: "ENCCS", 0xB1: "ENCDI", 0xB2: "ENCDO",
    }
    bit_names = {}
    entries = [0x0000]
    visited = recursive_disasm(mem, present, entries, sfr_names, bit_names)
    print(format_listing(visited))
