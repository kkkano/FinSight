# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')

with open(r'D:\AgentProject\FinSight\backend\graph\nodes\synthesize.py', encoding='utf-8') as f:
    lines = f.readlines()

line = lines[675]
print(f"Line 676: {line.rstrip()}")
print(f"  repr: {line.rstrip()!r}")
print()
for i, c in enumerate(line):
    if ord(c) > 127 or c == '"':
        print(f"  pos={i:3d} char={c!r:<6} unicode=U+{ord(c):04X} name={c}")

print()
# Also check original
with open(r'D:\AgentProject\FinSight\scripts\synthesize_original.py', encoding='utf-8') as f:
    orig_lines = f.readlines()

# Find original line with 生成研报
for idx, line in enumerate(orig_lines):
    if '生成研报' in line and '点击' in line:
        print(f"\nOriginal line {idx+1}: {line.rstrip()}")
        for i, c in enumerate(line):
            if ord(c) > 127 or c == '"':
                print(f"  pos={i:3d} char={c!r:<6} unicode=U+{ord(c):04X}")
        break
