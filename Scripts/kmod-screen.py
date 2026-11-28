#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kmod-screen.py — 全库包级正反向依赖筛查（先建图、后标记、再剔除）。

与旧 kmod-closure.py 的区别：
  旧流程：正则/黑名单先批量砍包 → 再跑闭环尝试救回，时序上容易漏救链路。
  本流程：
    1. 解析全部 KernelPackage 的 DEPENDS，并展开 AddDepends 宏带出的依赖；
    2. 建正向图 A→B、反向图 B←A；
    3. 以当前 .config 选中集 + PROTECT 保护根为种子，正向扩散闭包，全部标【必留】；
    4. 反向校验：必留包依赖到的包必须仍在集中，否则报错列出（防误剔）；
    5. 分类输出：必留 / 可剔（非必留且反向 0 引用）/ 存疑（非必留但被反向引用，保守保留）。

口径：
  - 不设任何“内建数量 ≥N”门槛；保留集合由种子 + 传递依赖 + 保护根精确决定，不多不少。
  - 包层面抓不到的内核符号隐式依赖，需成功轮 .ko + Module.symvers 二次复核（见 step17 落表）。
  - 存疑项一律保留，不自动剔除。

用法（runner，cwd=./wrt）：
  python3 Scripts/kmod-screen.py            # 只筛查 + 打印报表，不改 .config
  python3 Scripts/kmod-screen.py --apply    # 把“可剔”类写回 .config（存疑/必留不动）
环境变量可覆盖路径：
  KMOD_CFG=.config  KMOD_MK_GLOB='package/kernel/linux/modules/*.mk'
"""
import re, glob, json, os, sys, argparse

CFG = os.environ.get('KMOD_CFG', '.config')
MK_GLOB = os.environ.get('KMOD_MK_GLOB', 'package/kernel/linux/modules/*.mk')

# 保护根：路由器命根链，强制必留，不参与剔除判断。
PROTECT = re.compile(
    r'^kmod-(mac80211|cfg80211|ath11k|ath11k-ahb|ath11k-firmware.*|'
    r'usb-core|usb-common|usb-storage|usb-net.*|usb-net-rtl8152|usb-net-cdc-ether|usb-wdm|usb-serial-option|'
    r'nf-.*|nft-.*|ipt-.*|ip6t-.*|netfilter.*|'
    r'crypto-.*|crc-.*|'
    r'dm.*|md.*|'
    r'fs-(ext4|vfat|exfat|f2fs|btrfs|cifs|nfs|nfsd|nls.*|fat.*|msdos.*|ntfs.*)|'
    r'watchdog.*|hwmon.*|thermal.*|i2c-core|i2c-algo-bit|i2c-gpio|spi.*|gpio.*|pinctrl.*|'
    r'ppp.*|pppoe|sched.*|lib-(crc|zstd|xxhash)|nls-.*|leds.*|button.*|input-core|'
    r'phy-.*|mdio.*|switch.*|dsa.*|regmap.*|mux.*|pcs-.*|sfp.*|ptp|net-selftests|'
    r'block.*|mbcache|loop|nbd|scsi-core|sd-mod|usb-serial.*|tun|wireguard|vxlan|veth|bonding|bridge|'
    r'inet-diag|netlink-diag|xdp-sockets-diag)$'
)

MUST = ['kmod-mac80211', 'kmod-cfg80211', 'kmod-ath11k', 'kmod-ath11k-ahb']

COND = re.compile(r'^[A-Za-z0-9_.()-]+:')
PLACEHOLDER = {'$(1)', '$(cp)', '$(foreach', '$(call)'}


def clean_tokens(s):
    """从 DEPENDS 字符串提取包名 token，去掉平台条件/条件前缀/宏占位。"""
    s = s.replace('\\', ' ')
    out = []
    for tok in s.split():
        if tok in PLACEHOLDER or tok.startswith('@'):
            continue
        tok = COND.sub('', tok).lstrip('+')
        if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', tok):
            out.append(tok)
    return out


def load_macros(files):
    """抽 define AddDepends/<name> 宏体里的 DEPENDS+= 模板。"""
    macros = {}
    for f in files:
        txt = open(f, errors='ignore').read()
        for m in re.finditer(r'define AddDepends/([A-Za-z0-9_-]+)\n(.*?)\nendef', txt, re.S):
            body = m.group(2)
            tmpl = ' '.join(
                ln.strip()[len('DEPENDS+='):].strip()
                for ln in body.splitlines() if ln.strip().startswith('DEPENDS+=')
            )
            macros[m.group(1)] = tmpl
    return macros


def parse_packages(files, macros):
    deps, unresolved = {}, set()
    for f in files:
        txt = open(f, errors='ignore').read()
        for m in re.finditer(r'define KernelPackage/([A-Za-z0-9_.-]+)\n(.*?)\nendef', txt, re.S):
            pkg, body = 'kmod-' + m.group(1), m.group(2)
            ds = []
            for dm in re.finditer(r'DEPENDS:=\s*(.*?)(?=\n\s*[A-Z_]+:=\n|\nendef|\Z)', body, re.S):
                ds += clean_tokens(dm.group(1))
            for cm in re.finditer(r'\$\(call AddDepends/([A-Za-z0-9_-]+)(?:,\s*(.*?))?\)', body):
                name, args = cm.group(1), cm.group(2) or ''
                if name in macros:
                    tmpl = macros[name].replace('$(1)', args)
                    ds += clean_tokens(tmpl) + clean_tokens(args)
                else:
                    unresolved.add(name)
            seen, dd = set(), []
            for x in ds:
                if x not in seen:
                    seen.add(x); dd.append(x)
            deps[pkg] = dd
    return deps, unresolved


def load_selected(cfg):
    sel = {}
    if not os.path.exists(cfg):
        return sel
    for ln in open(cfg, errors='ignore'):
        m = re.match(r'^CONFIG_PACKAGE_([A-Za-z0-9_.+-]+)=([ym])$', ln.strip())
        if m:
            sel[m.group(1)] = m.group(2)
    return sel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='把可剔类写回 .config（默认只出报表）')
    ap.add_argument('--json', help='把分类结果写到指定 JSON 文件')
    args = ap.parse_args()

    files = sorted(glob.glob(MK_GLOB))
    macros = load_macros(files)
    deps, unresolved = parse_packages(files, macros)
    rev = {}
    for p, ds in deps.items():
        for d in ds:
            rev.setdefault(d, []).append(p)

    sel = load_selected(CFG)
    sel_k = {k for k in sel if k.startswith('kmod-')}
    defined = set(deps)

    # 种子：当前选中 kmod + 保护根命中
    protect_hit = {p for p in defined if PROTECT.match(p)}
    seed = sel_k | protect_hit

    # 正向闭包扩散
    closure = set(seed)
    stack = list(seed)
    while stack:
        n = stack.pop()
        for d in deps.get(n, []):
            if d not in closure:
                closure.add(d); stack.append(d)
    keep = closure

    # 分类
    drop, suspect = [], []
    for p in defined:
        if p in keep:
            continue
        if rev.get(p):
            suspect.append(p)
        else:
            drop.append(p)
    drop.sort(); suspect.sort()

    # 反向校验：必留包依赖到的包若不在 keep 且不在已知外部包，列出告警
    missing = []
    for p in keep:
        for d in deps.get(p, []):
            if d not in keep and d not in defined:
                missing.append((p, d))

    print(f'解析 .mk 文件: {len(files)}  KernelPackage 定义: {len(deps)}')
    print(f'选中 kmod(.config): {len(sel_k)}  保护根命中: {len(protect_hit)}')
    print(f'必留闭包: {len(keep)}  可剔(反向0): {len(drop)}  存疑(被反向引用,保留): {len(suspect)}')
    if unresolved:
        print(f'警告: 未解析 AddDepends 宏: {sorted(unresolved)}')
    if missing:
        print('告警: 必留包依赖到未定义/外部包（需符号级或 feeds 复核）:')
        for p, d in sorted(missing)[:40]:
            print(f'  {p} -> {d}')

    # 命根断言
    bad = [m for m in MUST if m not in sel and m not in keep]
    if bad:
        print(f'失败: 命根包缺失 {bad}')
        sys.exit(1)
    print('命根校验通过:', ' '.join(MUST))

    if args.json:
        json.dump({'keep': sorted(keep), 'drop': drop, 'suspect': suspect,
                   'protect': sorted(protect_hit), 'missing': missing},
                  open(args.json, 'w'), ensure_ascii=False, indent=1)

    if args.apply:
        lines = open(CFG, errors='ignore').read().splitlines()
        for p in drop:
            rx = re.compile(rf'^CONFIG_PACKAGE_{re.escape(p)}=[ym]$')
            lines = [rx.sub(f'# CONFIG_PACKAGE_{p} is not set', ln) for ln in lines]
        open(CFG, 'w').write('\n'.join(lines) + '\n')
        print(f'已写回 .config: 剔除 {len(drop)} 个可剔包；存疑 {len(suspect)} 个保留未动')

    print('\n=== 可剔候选（静态反向 0，待符号级复核）===')
    for p in drop:
        print(' ', p)
    print('\n=== 存疑（被反向引用，保守保留）===')
    for p in suspect:
        print(' ', p)


if __name__ == '__main__':
    main()
