#!/usr/bin/env python3
import re
import sys

#TARGETS = ["4301", "430C", "4318", "4342", "4644", "46D9"]
TARGETS = ["4142", "452E", "4784"]

if len(sys.argv) != 2:
    print(f"Uso: {sys.argv[0]} full_disasm.txt")
    sys.exit(1)

path = sys.argv[1]

with open(path, "r", encoding="utf-8", errors="replace") as f:
    lines = f.readlines()

for target in TARGETS:
    # cerca "4301:" oppure "4301 :" ecc.
    pat = re.compile(rf"^\s*{target}\s*:")
    start = next((i for i, line in enumerate(lines) if pat.match(line)), None)

    if start is None:
        print(f"\n===== {target}: NON TROVATA =====")
        continue

    end = None
    for i in range(start, len(lines)):
        # RET = 22, RETI = 32
        if re.search(r"\b(?:RET|RETI)\b", lines[i], re.IGNORECASE):
            end = i
            break

    if end is None:
        end = min(start + 100, len(lines) - 1)

    print(f"\n===== ROUTINE {target} =====")
    print("".join(lines[start:end + 1]), end="")