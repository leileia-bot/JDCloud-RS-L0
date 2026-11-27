#!/usr/bin/env python3
"""整族依赖闭环：把"依赖已被剔除"的 kmod 一并剔除，避免打包阶段 missing *.ko。
依据 package/kernel/linux/modules/*.mk 里的 DEPENDS 声明，迭代到不动点。
"""
import re, glob, sys

cfg = '.config'
sel = set()
for ln in open(cfg, errors='ignore'):
    m = re.match(r'^CONFIG_PACKAGE_([A-Za-z0-9_.+-]+)=[ym]$', ln.strip())
    if m:
        sel.add(m.group(1))

deps = {}
for f in glob.glob('package/kernel/linux/modules/*.mk'):
    txt = open(f, errors='ignore').read()
    for blk in re.split(r'\n(?=define KernelPackage)', txt):
        m = re.match(r'define KernelPackage/([A-Za-z0-9_.+-]+)', blk)
        if not m:
            continue
        name = 'kmod-' + m.group(1)
        dl = []
        for line in re.findall(r'DEPENDS\s*:?=\s*(.*)', blk):
            for tok in line.replace('\\', ' ').split():
                if not tok.startswith('+'):
                    continue
                t = tok[1:].strip()
                if re.fullmatch(r'[A-Za-z0-9_.+-]+', t):
                    dl.append(t)
        deps[name] = dl
print(f"解析到 {len(deps)} 个 kmod 的依赖声明")

drop = []
changed = True
while changed:
    changed = False
    for name, d in deps.items():
        if name not in sel:
            continue
        missing = [x for x in d if x not in sel]
        if missing:
            sel.discard(name)
            drop.append((name, missing[0]))
            changed = True

for name, miss in drop:
    print(f"  连带剔除 {name}（依赖 {miss} 已不在选中集）")

if drop:
    txt = open(cfg, errors='ignore').read()
    for name, _ in drop:
        txt = re.sub(rf'^CONFIG_PACKAGE_{re.escape(name)}=[ym]$',
                     f'# CONFIG_PACKAGE_{name} is not set', txt, flags=re.M)
    open(cfg, 'w').write(txt)
print(f"闭环共剔除 {len(drop)} 个包")
