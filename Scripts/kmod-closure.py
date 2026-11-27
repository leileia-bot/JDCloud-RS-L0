#!/usr/bin/env python3
"""整族依赖闭环 v2：先"救"路由器命根依赖，再剔"没人要"的孤儿包。

规则：
1. 以保护清单（网络/存储/代理/WiFi/温度/watchdog）为根，把它们依赖的链全部标记为"必需"，
   凡是被剔掉的必需依赖，一律加回 =y —— 避免"删了本该留的东西"。
2. 其余被选中、但依赖已不存在的 kmod，连带剔除（避免打包 missing *.ko）。
3. 迭代到不动点。
"""
import re, glob

cfg = '.config'
PROTECT = re.compile(
    r'^kmod-(mac80211|cfg80211|ath11k|ath11k-ahb|ath11k-firmware.*|'
    r'usb-core|usb-common|usb-storage|usb-net.*|'
    r'nf-.*|nft-.*|ipt-.*|ip6t-.*|netfilter.*|'
    r'crypto-.*|crc-.*|'
    r'dm.*|md.*|'
    r'fs-(ext4|vfat|exfat|f2fs|btrfs|cifs|nfs|nfsd|nls.*|fat.*|msdos.*|ntfs.*)|'
    r'watchdog.*|hwmon.*|thermal.*|i2c-core|i2c-algo-bit|i2c-gpio|spi.*|gpio.*|pinctrl.*|'
    r'ppp.*|pppoe|sched.*|lib-(crc|zstd|xxhash)|nls-.*|leds.*|button.*|input-core|'
    r'phy-.*|mdio.*|switch.*|dsa-.*|regmap.*|mux.*|pcs-.*|sfp.*|'
    r'block.*|mbcache|loop|nbd|scsi-core|sd-mod|usb-serial.*|tun|wireguard|vxlan|veth|bonding|bridge)$'
)

def parse_sel(path):
    sel = {}
    for ln in open(path, errors='ignore'):
        m = re.match(r'^CONFIG_PACKAGE_([A-Za-z0-9_.+-]+)=([ym])$', ln.strip())
        if m:
            sel[m.group(1)] = m.group(2)
    return sel

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

sel = parse_sel(cfg)
print(f"解析 {len(deps)} 个 kmod 依赖声明；当前选中 {len(sel)} 个包")

# --- 第 1 步：救回保护链 ---
need = set()
stack = [n for n in sel if PROTECT.match(n)]
root = set(stack)
while stack:
    n = stack.pop()
    for d in deps.get(n, []):
        if d not in need:
            need.add(d)
            stack.append(d)

dropped_present = [n for n in need if n not in sel and n in deps]
restored = []
lines = open(cfg, errors='ignore').read().splitlines()
if dropped_present:
    for n in dropped_present:
        entry = f'CONFIG_PACKAGE_{n}=y'
        txt = '\n'.join(lines)
        txt = re.sub(rf'^# CONFIG_PACKAGE_{re.escape(n)} is not set$', entry, txt, flags=re.M)
        lines = txt.splitlines()
        restored.append(n)
    open(cfg, 'w').write('\n'.join(lines) + '\n')
    sel = parse_sel(cfg)
for n in restored:
    print(f"  加回 {n}（路由器命根依赖链上的必需件）")

# --- 第 2 步：剔孤儿 ---
drop = []
changed = True
while changed:
    changed = False
    for name, d in deps.items():
        if name not in sel or name in root:
            continue
        missing = [x for x in d if x not in sel]
        if missing:
            sel.pop(name, None)
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

print(f"闭环结果：加回 {len(restored)} 个，剔除 {len(drop)} 个")

# --- 第 3 步：命根断言 ---
must = ['kmod-mac80211', 'kmod-cfg80211', 'kmod-ath11k', 'kmod-ath11k-ahb']
bad = [m for m in must if m not in sel]
if bad:
    print(f"失败: 命根包缺失 {bad}")
    raise SystemExit(1)
print("命根校验通过:", ' '.join(must))
