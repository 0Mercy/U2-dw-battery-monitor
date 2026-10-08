"""Static PE inspection only. Never loads or executes the inspected executable."""
import argparse
import bisect
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).parent / '_analysis_deps'))
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64
from capstone.x86 import X86_OP_MEM, X86_REG_RIP, X86_OP_IMM

SOURCE = Path(__file__).parent.parent / 'ZOWIE v2524_DW_FW_Update_Tool.exe'
pe = pefile.PE(str(SOURCE), fast_load=True)
pe.parse_data_directories(directories=[3])
base = pe.OPTIONAL_HEADER.ImageBase
functions = [(e.struct.BeginAddress, e.struct.EndAddress) for e in pe.DIRECTORY_ENTRY_EXCEPTION]
starts = [f[0] for f in functions]
decoder = Cs(CS_ARCH_X86, CS_MODE_64)
decoder.detail = True


def owner(rva):
    index = bisect.bisect_right(starts, rva) - 1
    return functions[index] if index >= 0 and rva < functions[index][1] else (rva, rva + 128)


def disassemble(start, end):
    return decoder.disasm(pe.get_data(start, end - start), base + start)


def references(start, end):
    for begin, finish in functions:
        if not start <= begin < end:
            continue
        for instruction in disassemble(begin, finish):
            for operand in instruction.operands:
                target = None
                if operand.type == X86_OP_MEM and operand.mem.base == X86_REG_RIP:
                    target = instruction.address + instruction.size + operand.mem.disp
                elif operand.type == X86_OP_IMM and instruction.mnemonic in ('call', 'jmp'):
                    target = operand.imm
                if target is not None:
                    yield {'rva': instruction.address - base, 'function': begin,
                           'target': target - base, 'instruction': f'{instruction.mnemonic} {instruction.op_str}'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['refs', 'function', 'strings'])
    parser.add_argument('values', nargs='*')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.action == 'refs':
        start, end = [int(v, 0) for v in args.values]
        output = json.dumps(list(references(start, end)))
    elif args.action == 'function':
        lines = []
        for value in args.values:
            start, end = owner(int(value, 0))
            lines.append(f'FUNCTION {start:#x}..{end:#x}')
            for instruction in disassemble(start, end):
                lines.append(f'{instruction.address - base:08x}: {instruction.mnemonic:8s} {instruction.op_str}')
        output = '\n'.join(lines)
    else:
        pattern = re.compile(args.values[0], re.IGNORECASE)
        data = SOURCE.read_bytes()
        rows = []
        for match in re.finditer(rb'[ -~]{4,}', data):
            value = match.group().decode('ascii')
            if pattern.search(value):
                rows.append({'offset': match.start(), 'rva': pe.get_rva_from_offset(match.start()), 'text': value})
        output = json.dumps(rows, indent=2)
    if args.out:
        args.out.write_text(output, encoding='utf-8')
    else:
        print(output)
