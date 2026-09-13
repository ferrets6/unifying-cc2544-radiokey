#!/usr/bin/env python3
"""
Independent minimal 8051 disassembler, written from scratch for this task.
Does not reuse any pre-existing tool in this repo.

Usage: python indep_disasm.py fw.bin [start] [end]
"""
import sys

# Opcode table: opcode -> (mnemonic, length, operand-format)
# operand-format tokens are filled in disassemble()
# We implement the full standard 8051 instruction set (255 defined opcodes,
# 0xA5 reserved/undefined on plain 8051).

REG = ['R0','R1','R2','R3','R4','R5','R6','R7']

def bit_addr_name(b):
    # bit-addressable area: 0x20-0x2F (bits 0x00-0x7F), and bit-addressable SFRs
    if 0x00 <= b <= 0x7F:
        byte_addr = 0x20 + (b >> 3)
        bit_num = b & 7
        return f"{byte_addr:#04x}.{bit_num}"
    else:
        byte_addr = b & 0xF8
        bit_num = b & 7
        return f"{byte_addr:#04x}.{bit_num}"

def rel_target(pc_after, rel):
    if rel >= 0x80:
        rel -= 0x100
    return (pc_after + rel) & 0xFFFF

class Insn:
    def __init__(self, addr, length, mnem, bytes_):
        self.addr = addr
        self.length = length
        self.mnem = mnem
        self.bytes = bytes_
    def __str__(self):
        hexb = ' '.join(f'{b:02X}' for b in self.bytes)
        return f"{self.addr:04X}: {hexb:<12} {self.mnem}"

def disasm_one(data, pc):
    op = data[pc]
    def b(i):
        return data[pc+i]

    # single-byte, no operand
    simple = {
        0x00: 'NOP',
        0x22: 'RET',
        0x32: 'RETI',
        0x83: 'MOVC A,@A+PC',
        0x93: 'MOVC A,@A+DPTR',
        0xE0: 'MOVX A,@DPTR',
        0xF0: 'MOVX @DPTR,A',
        0xE2: 'MOVX A,@R0',
        0xE3: 'MOVX A,@R1',
        0xF2: 'MOVX @R0,A',
        0xF3: 'MOVX @R1,A',
        0xA3: 'INC DPTR',
        0xD0: 'POP ??',  # handled below actually needs operand; placeholder unused
        0x84: 'DIV AB',
        0xA4: 'MUL AB',
        0xD4: 'DA A',
        0x23: 'RL A',
        0x33: 'RLC A',
        0x03: 'RR A',
        0x13: 'RRC A',
        0xF4: 'CPL A',
        0xE4: 'CLR A',
        0xC4: 'SWAP A',
        0xD3: 'SETB C',
        0xC3: 'CLR C',
        0xB3: 'CPL C',
        0x00+0x00: 'NOP',
    }

    A_arith = {0x24:'ADD',0x34:'ADDC',0x94:'SUBB'}

    # A,Rn (0x28-0x2F etc groups): handled via base+reg pattern
    def group(base_add, base_reg_direct, base_reg_indirect_r0, base_reg_indirect_r1,
               base_reg_imm, mnem):
        pass

    hi = op & 0xF8
    lo = op & 0x07

    # MOV Rn, direct  (0xA8-0xAF)  -- MOV Rn,direct
    if 0xA8 <= op <= 0xAF and op != 0xA8+0:
        pass

    # --- big dispatch ---
    # 1-byte fixed instructions
    fixed1 = {
        0x00:'NOP', 0x22:'RET', 0x32:'RETI', 0x83:'MOVC A,@A+PC',
        0x93:'MOVC A,@A+DPTR', 0xE0:'MOVX A,@DPTR', 0xF0:'MOVX @DPTR,A',
        0xE2:'MOVX A,@R0', 0xE3:'MOVX A,@R1', 0xF2:'MOVX @R0,A', 0xF3:'MOVX @R1,A',
        0xA3:'INC DPTR', 0x84:'DIV AB', 0xA4:'MUL AB', 0xD4:'DA A',
        0x23:'RL A', 0x33:'RLC A', 0x03:'RR A', 0x13:'RRC A',
        0xF4:'CPL A', 0xE4:'CLR A', 0xC4:'SWAP A',
        0xD3:'SETB C', 0xC3:'CLR C', 0xB3:'CPL C', 0x9F: None,
    }
    if op in fixed1 and fixed1[op] is not None:
        m = fixed1[op]
        return Insn(pc, 1, m, data[pc:pc+1])

    # INC A / DEC A
    if op == 0x04: return Insn(pc,1,'INC A', data[pc:pc+1])
    if op == 0x14: return Insn(pc,1,'DEC A', data[pc:pc+1])
    # INC Rn (0x08-0x0F), DEC Rn (0x18-0x1F)
    if 0x08 <= op <= 0x0F: return Insn(pc,1,f'INC {REG[op-0x08]}', data[pc:pc+1])
    if 0x18 <= op <= 0x1F: return Insn(pc,1,f'DEC {REG[op-0x18]}', data[pc:pc+1])
    # INC @Ri (0x06,0x07), DEC @Ri (0x16,0x17)
    if op in (0x06,0x07): return Insn(pc,1,f'INC @R{op-0x06}', data[pc:pc+1])
    if op in (0x16,0x17): return Insn(pc,1,f'DEC @R{op-0x16}', data[pc:pc+1])

    # INC direct 0x05, DEC direct 0x15
    if op == 0x05:
        d = b(1); return Insn(pc,2,f'INC {d:#04x}', data[pc:pc+2])
    if op == 0x15:
        d = b(1); return Insn(pc,2,f'DEC {d:#04x}', data[pc:pc+2])

    # ADD/ADDC/SUBB A,#imm  ADD A,#imm=0x24 ADDC=0x34 SUBB=0x94
    if op == 0x24: d=b(1); return Insn(pc,2,f'ADD A,#{d:#04x}', data[pc:pc+2])
    if op == 0x34: d=b(1); return Insn(pc,2,f'ADDC A,#{d:#04x}', data[pc:pc+2])
    if op == 0x94: d=b(1); return Insn(pc,2,f'SUBB A,#{d:#04x}', data[pc:pc+2])
    # ADD/ADDC/SUBB A,direct = 0x25/0x35/0x95
    if op == 0x25: d=b(1); return Insn(pc,2,f'ADD A,{d:#04x}', data[pc:pc+2])
    if op == 0x35: d=b(1); return Insn(pc,2,f'ADDC A,{d:#04x}', data[pc:pc+2])
    if op == 0x95: d=b(1); return Insn(pc,2,f'SUBB A,{d:#04x}', data[pc:pc+2])
    # ADD/ADDC/SUBB A,@Ri = 0x26/0x27 (ADD), 0x36/0x37(ADDC), 0x96/0x97(SUBB)
    if op in (0x26,0x27): return Insn(pc,1,f'ADD A,@R{op-0x26}', data[pc:pc+1])
    if op in (0x36,0x37): return Insn(pc,1,f'ADDC A,@R{op-0x36}', data[pc:pc+1])
    if op in (0x96,0x97): return Insn(pc,1,f'SUBB A,@R{op-0x96}', data[pc:pc+1])
    # ADD/ADDC/SUBB A,Rn = 0x28-0x2F / 0x38-0x3F / 0x98-0x9F
    if 0x28 <= op <= 0x2F: return Insn(pc,1,f'ADD A,{REG[op-0x28]}', data[pc:pc+1])
    if 0x38 <= op <= 0x3F: return Insn(pc,1,f'ADDC A,{REG[op-0x38]}', data[pc:pc+1])
    if 0x98 <= op <= 0x9F: return Insn(pc,1,f'SUBB A,{REG[op-0x98]}', data[pc:pc+1])

    # ORL / ANL / XRL variants
    # ORL direct,A =0x42 ; ORL direct,#imm=0x43 ; ORL A,#imm=0x44; ORL A,direct=0x45
    # ORL A,@Ri=0x46/0x47 ; ORL A,Rn=0x48-0x4F
    if op == 0x42: d=b(1); return Insn(pc,2,f'ORL {d:#04x},A', data[pc:pc+2])
    if op == 0x43: d=b(1); i=b(2); return Insn(pc,3,f'ORL {d:#04x},#{i:#04x}', data[pc:pc+3])
    if op == 0x44: i=b(1); return Insn(pc,2,f'ORL A,#{i:#04x}', data[pc:pc+2])
    if op == 0x45: d=b(1); return Insn(pc,2,f'ORL A,{d:#04x}', data[pc:pc+2])
    if op in (0x46,0x47): return Insn(pc,1,f'ORL A,@R{op-0x46}', data[pc:pc+1])
    if 0x48 <= op <= 0x4F: return Insn(pc,1,f'ORL A,{REG[op-0x48]}', data[pc:pc+1])

    if op == 0x52: d=b(1); return Insn(pc,2,f'ANL {d:#04x},A', data[pc:pc+2])
    if op == 0x53: d=b(1); i=b(2); return Insn(pc,3,f'ANL {d:#04x},#{i:#04x}', data[pc:pc+3])
    if op == 0x54: i=b(1); return Insn(pc,2,f'ANL A,#{i:#04x}', data[pc:pc+2])
    if op == 0x55: d=b(1); return Insn(pc,2,f'ANL A,{d:#04x}', data[pc:pc+2])
    if op in (0x56,0x57): return Insn(pc,1,f'ANL A,@R{op-0x56}', data[pc:pc+1])
    if 0x58 <= op <= 0x5F: return Insn(pc,1,f'ANL A,{REG[op-0x58]}', data[pc:pc+1])

    if op == 0x62: d=b(1); return Insn(pc,2,f'XRL {d:#04x},A', data[pc:pc+2])
    if op == 0x63: d=b(1); i=b(2); return Insn(pc,3,f'XRL {d:#04x},#{i:#04x}', data[pc:pc+3])
    if op == 0x64: i=b(1); return Insn(pc,2,f'XRL A,#{i:#04x}', data[pc:pc+2])
    if op == 0x65: d=b(1); return Insn(pc,2,f'XRL A,{d:#04x}', data[pc:pc+2])
    if op in (0x66,0x67): return Insn(pc,1,f'XRL A,@R{op-0x66}', data[pc:pc+1])
    if 0x68 <= op <= 0x6F: return Insn(pc,1,f'XRL A,{REG[op-0x68]}', data[pc:pc+1])

    # ORL C,bit = 0x72 ; ORL C,/bit = 0xA0 ; ANL C,bit = 0x82 ; ANL C,/bit=0xB0
    if op == 0x72: bt=b(1); return Insn(pc,2,f'ORL C,{bit_addr_name(bt)}', data[pc:pc+2])
    if op == 0xA0: bt=b(1); return Insn(pc,2,f'ORL C,/{bit_addr_name(bt)}', data[pc:pc+2])
    if op == 0x82: bt=b(1); return Insn(pc,2,f'ANL C,{bit_addr_name(bt)}', data[pc:pc+2])
    if op == 0xB0: bt=b(1); return Insn(pc,2,f'ANL C,/{bit_addr_name(bt)}', data[pc:pc+2])

    # MOV direct,#imm = 0x75 ; MOV direct,direct = 0x85 (src,dst order is dest,src actually direct2<-direct1 weird)
    if op == 0x75: d=b(1); i=b(2); return Insn(pc,3,f'MOV {d:#04x},#{i:#04x}', data[pc:pc+3])
    if op == 0x76 or op == 0x77:
        i=b(1); return Insn(pc,2,f'MOV @R{op-0x76},#{i:#04x}', data[pc:pc+2])
    if 0x78 <= op <= 0x7F:
        i=b(1); return Insn(pc,2,f'MOV {REG[op-0x78]},#{i:#04x}', data[pc:pc+2])
    if op == 0x85:
        d1=b(1); d2=b(2)
        # MOV direct2, direct1 ; encoding is (src)(dst) -> "MOV dst,src" ; datasheet: MOV direct,direct ; opcode d1(src) d2(dest)? Actually 8051: 85 src dest -> MOV dest,src
        return Insn(pc,3,f'MOV {d2:#04x},{d1:#04x}', data[pc:pc+3])
    if op in (0x86,0x87):
        d=b(1); return Insn(pc,2,f'MOV {d:#04x},@R{op-0x86}', data[pc:pc+2])
    if 0x88 <= op <= 0x8F:
        d=b(1); return Insn(pc,2,f'MOV {d:#04x},{REG[op-0x88]}', data[pc:pc+2])
    if op == 0x90:
        hi_=b(1); lo_=b(2); return Insn(pc,3,f'MOV DPTR,#{(hi_<<8)|lo_:#06x}', data[pc:pc+3])
    if op == 0x92:
        bt=b(1); return Insn(pc,2,f'MOV {bit_addr_name(bt)},C', data[pc:pc+2])
    if op == 0xA2:
        bt=b(1); return Insn(pc,2,f'MOV C,{bit_addr_name(bt)}', data[pc:pc+2])
    if op in (0xA6,0xA7):
        d=b(1); return Insn(pc,2,f'MOV @R{op-0xA6},{d:#04x}', data[pc:pc+2])
    if 0xA8 <= op <= 0xAF:
        d=b(1); return Insn(pc,2,f'MOV {REG[op-0xA8]},{d:#04x}', data[pc:pc+2])
    if op == 0xE5:
        d=b(1); return Insn(pc,2,f'MOV A,{d:#04x}', data[pc:pc+2])
    if op in (0xE6,0xE7):
        return Insn(pc,1,f'MOV A,@R{op-0xE6}', data[pc:pc+1])
    if 0xE8 <= op <= 0xEF:
        return Insn(pc,1,f'MOV A,{REG[op-0xE8]}', data[pc:pc+1])
    if op == 0xF5:
        d=b(1); return Insn(pc,2,f'MOV {d:#04x},A', data[pc:pc+2])
    if op in (0xF6,0xF7):
        return Insn(pc,1,f'MOV @R{op-0xF6},A', data[pc:pc+1])
    if 0xF8 <= op <= 0xFF:
        return Insn(pc,1,f'MOV {REG[op-0xF8]},A', data[pc:pc+1])
    if op == 0x74:
        i=b(1); return Insn(pc,2,f'MOV A,#{i:#04x}', data[pc:pc+2])

    # SETB / CLR / CPL bit
    if op == 0xD2: bt=b(1); return Insn(pc,2,f'SETB {bit_addr_name(bt)}', data[pc:pc+2])
    if op == 0xC2: bt=b(1); return Insn(pc,2,f'CLR {bit_addr_name(bt)}', data[pc:pc+2])
    if op == 0xB2: bt=b(1); return Insn(pc,2,f'CPL {bit_addr_name(bt)}', data[pc:pc+2])

    # PUSH/POP
    if op == 0xC0: d=b(1); return Insn(pc,2,f'PUSH {d:#04x}', data[pc:pc+2])
    if op == 0xD0: d=b(1); return Insn(pc,2,f'POP {d:#04x}', data[pc:pc+2])

    # XCH / XCHD
    if op == 0xC5: d=b(1); return Insn(pc,2,f'XCH A,{d:#04x}', data[pc:pc+2])
    if op in (0xC6,0xC7): return Insn(pc,1,f'XCH A,@R{op-0xC6}', data[pc:pc+1])
    if 0xC8 <= op <= 0xCF: return Insn(pc,1,f'XCH A,{REG[op-0xC8]}', data[pc:pc+1])
    if op in (0xD6,0xD7): return Insn(pc,1,f'XCHD A,@R{op-0xD6}', data[pc:pc+1])

    # CJNE variants: A,#imm,rel=0xB4 ; A,direct,rel=0xB5 ; @Ri,#imm,rel=0xB6/0xB7 ; Rn,#imm,rel=0xB8-0xBF
    if op == 0xB4:
        i=b(1); rel=b(2); tgt=rel_target(pc+3,rel)
        return Insn(pc,3,f'CJNE A,#{i:#04x},{tgt:#06x}', data[pc:pc+3])
    if op == 0xB5:
        d=b(1); rel=b(2); tgt=rel_target(pc+3,rel)
        return Insn(pc,3,f'CJNE A,{d:#04x},{tgt:#06x}', data[pc:pc+3])
    if op in (0xB6,0xB7):
        i=b(1); rel=b(2); tgt=rel_target(pc+3,rel)
        return Insn(pc,3,f'CJNE @R{op-0xB6},#{i:#04x},{tgt:#06x}', data[pc:pc+3])
    if 0xB8 <= op <= 0xBF:
        i=b(1); rel=b(2); tgt=rel_target(pc+3,rel)
        return Insn(pc,3,f'CJNE {REG[op-0xB8]},#{i:#04x},{tgt:#06x}', data[pc:pc+3])

    # DJNZ direct,rel=0xD5 ; DJNZ Rn,rel=0xD8-0xDF
    if op == 0xD5:
        d=b(1); rel=b(2); tgt=rel_target(pc+3,rel)
        return Insn(pc,3,f'DJNZ {d:#04x},{tgt:#06x}', data[pc:pc+3])
    if 0xD8 <= op <= 0xDF:
        rel=b(1); tgt=rel_target(pc+2,rel)
        return Insn(pc,2,f'DJNZ {REG[op-0xD8]},{tgt:#06x}', data[pc:pc+2])

    # JZ/JNZ rel
    if op == 0x60: rel=b(1); tgt=rel_target(pc+2,rel); return Insn(pc,2,f'JZ {tgt:#06x}', data[pc:pc+2])
    if op == 0x70: rel=b(1); tgt=rel_target(pc+2,rel); return Insn(pc,2,f'JNZ {tgt:#06x}', data[pc:pc+2])
    # JC/JNC rel
    if op == 0x40: rel=b(1); tgt=rel_target(pc+2,rel); return Insn(pc,2,f'JC {tgt:#06x}', data[pc:pc+2])
    if op == 0x50: rel=b(1); tgt=rel_target(pc+2,rel); return Insn(pc,2,f'JNC {tgt:#06x}', data[pc:pc+2])
    # JB/JNB bit,rel ; JBC bit,rel
    if op == 0x20: bt=b(1); rel=b(2); tgt=rel_target(pc+3,rel); return Insn(pc,3,f'JB {bit_addr_name(bt)},{tgt:#06x}', data[pc:pc+3])
    if op == 0x30: bt=b(1); rel=b(2); tgt=rel_target(pc+3,rel); return Insn(pc,3,f'JNB {bit_addr_name(bt)},{tgt:#06x}', data[pc:pc+3])
    if op == 0x10: bt=b(1); rel=b(2); tgt=rel_target(pc+3,rel); return Insn(pc,3,f'JBC {bit_addr_name(bt)},{tgt:#06x}', data[pc:pc+3])
    # JMP @A+DPTR
    if op == 0x73: return Insn(pc,1,'JMP @A+DPTR', data[pc:pc+1])
    # SJMP rel
    if op == 0x80: rel=b(1); tgt=rel_target(pc+2,rel); return Insn(pc,2,f'SJMP {tgt:#06x}', data[pc:pc+2])
    # AJMP / ACALL: 11-bit addr, opcode form a10a9a800001 where top3 bits + 00001/10001 pattern
    if (op & 0x1F) == 0x01:  # AJMP: bits pattern a10 a9 a8 00001
        a10_8 = (op >> 5) & 0x07
        lo8 = b(1)
        page = (pc+2) & 0xF800
        tgt = page | (a10_8 << 8) | lo8
        return Insn(pc,2,f'AJMP {tgt:#06x}', data[pc:pc+2])
    if (op & 0x1F) == 0x11:  # ACALL
        a10_8 = (op >> 5) & 0x07
        lo8 = b(1)
        page = (pc+2) & 0xF800
        tgt = page | (a10_8 << 8) | lo8
        return Insn(pc,2,f'ACALL {tgt:#06x}', data[pc:pc+2])
    # LJMP / LCALL
    if op == 0x02:
        hi_=b(1); lo_=b(2); tgt=(hi_<<8)|lo_
        return Insn(pc,3,f'LJMP {tgt:#06x}', data[pc:pc+3])
    if op == 0x12:
        hi_=b(1); lo_=b(2); tgt=(hi_<<8)|lo_
        return Insn(pc,3,f'LCALL {tgt:#06x}', data[pc:pc+3])

    # unknown/reserved
    return Insn(pc,1,f'DB {op:#04x} ; UNKNOWN OPCODE', data[pc:pc+1])


def linear_disasm(data, start, end):
    pc = start
    out = []
    while pc < end:
        insn = disasm_one(data, pc)
        out.append(insn)
        pc += insn.length
    return out


if __name__ == '__main__':
    fn = sys.argv[1] if len(sys.argv) > 1 else 'fw.bin'
    start = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x0000
    end = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0x6400
    with open(fn, 'rb') as f:
        data = f.read()
    for insn in linear_disasm(data, start, min(end, len(data))):
        print(insn)
