#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kmod-symbol-audit.py — 符号级隐式依赖对账（离线，只读，不改 .config、不阻断编译）。

与包级 screen/closure 的分工：
  包级脚本只看 .mk 里声明的 DEPENDS（显式边）；本脚本从真实 .ko 的未定义符号
  （required_symbols）出发，对照 Module.symvers 的导出方，把包级看不到的
  符号级隐式边挖出来，兜底防止“砍掉某模块后，保留 .ko 运行时缺符号”。

输入（kmod-deps 落表目录 $OUT）：
  Module.symvers   CRC  符号  导出方(vmlinux|模块路径)  导出类型
  mods.tar.gz     全部内核 .ko（流式解，按 basename 去重）
  ko.list         主表 .ko 路径清单（产物集基准）
  Config/target_kmod.txt  保留包名基准（仅报表标注，可选）

符号分类：
  builtin        符号由 vmlinux 内建导出（一直在，安全）
  module         符号由某独立 .ko 导出，且该 .ko 在产物集内（正常）
  dropped        符号由某模块导出，但该模块 .ko 不在产物集（疑似被剔/丢失，重点查）
  unresolved     symvers 查不到导出方（外部库符号 / 编译器符号 / 真缺模块，需人工分）

数据源限制：unresolved 仅在 Module.symvers 已有覆盖范围内可信；若 symvers 本身
缺某模块导出（如无线栈 cfg80211/mac80211 符号未被抓取），会把跨驱动引用误报为
unresolved，不能直接判缺。dropped（导出方不在产物集）结论不受此影响。

用法：
  python3 kmod-symbol-audit.py <OUT> [--strict]
环境变量可覆盖：SYMVERS / MODS_TGZ / KO_LIST / TARGET_KMOD
"""
import os, sys, re, json, tarfile, subprocess, tempfile, argparse, collections

# 被剔六族（与 workflow / closure 口径一致），用于标注 dropped 导出方归属。
DROP_FAM = re.compile(
    r'(rt2800|rt2x00|rt61|rt73|dahdi|openvswitch|team|pse|'
    r'tpm-ftpm|tpm-i2c|tpm-tis)', re.I)

# unresolved 里常见的非内核引用噪音：编译器/段符号/局部符号，单列不计高危。
NOISE = re.compile(
    r'^(\$|__section_|__start_|__stop_|__crc_|__kstrtab|__initdata|'
    r'__aeabi|__clz|__ctz|__popcount|__udiv|__modti3|__ashl|__lshr|'
    r'_GLOBAL_OFFSET_TABLE_|__bss|__data|__rodata|__text)')


def load_symvers(path):
    """符号 -> 导出方；vmlinux 表示内建导出。"""
    sym2exp = {}
    if not os.path.exists(path):
        return sym2exp
    for ln in open(path, errors='ignore'):
        f = ln.split()
        if len(f) < 4:
            continue
        # 列: CRC 符号 导出方 导出类型 [命名空间]；导出方固定第 3 列(f[2])
        sym, exp = f[1], f[2]
        sym2exp[sym] = exp
    return sym2exp


def load_bases(path):
    s = set()
    if os.path.exists(path):
        for ln in open(path, errors='ignore'):
            ln = ln.strip()
            if ln:
                s.add(os.path.basename(ln))
    return s


def clean_sym(name):
    """去掉符号名尾部的 [索引]/版本@，返回干净符号名。"""
    name = name.split('[')[0].strip()
    name = re.sub(r'@\S*$', '', name).strip()
    return name


def undefined_symbols(ko_path):
    """readelf 取 .ko 的未定义（UND）符号名集合。"""
    out = set()
    try:
        r = subprocess.run(['readelf', '-sW', ko_path], capture_output=True,
                           text=True, timeout=30)
    except Exception as e:
        return out, f'readelf 失败: {e}'
    for ln in r.stdout.splitlines():
        c = ln.split()
        if len(c) < 8 or c[0].startswith('Symbol') or c[0] == 'Num:':
            continue
        # Num Value Size Type Bind Vis Ndx Name
        if c[6] == 'UND':
            sym = clean_sym(c[7])
            if sym:
                out.add(sym)
    return out, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out', nargs='?', default='.')
    ap.add_argument('--strict', action='store_true',
                    help='存在 dropped / 高危 unresolved 时退出 1（默认只读退出 0）')
    args = ap.parse_args()
    out = args.out

    symvers = os.environ.get('SYMVERS', os.path.join(out, 'Module.symvers'))
    mods = os.environ.get('MODS_TGZ', os.path.join(out, 'mods.tar.gz'))
    kolist = os.environ.get('KO_LIST', os.path.join(out, 'ko.list'))
    target = os.environ.get('TARGET_KMOD',
                            os.path.join(out, '..', 'Config', 'target_kmod.txt'))

    sym2exp = load_symvers(symvers)
    kos = load_bases(kolist)
    target_pkgs = {ln.strip() for ln in open(target, errors='ignore')
                    if ln.strip() and not ln.startswith('#')} if os.path.exists(target) else set()

    # 收集唯一 .ko（basename -> tar 内成员路径）
    seen = {}
    if os.path.exists(mods):
        with tarfile.open(mods, 'r:gz') as tf:
            for m in tf:
                if m.isfile() and m.name.endswith('.ko'):
                    b = os.path.basename(m.name)
                    if b not in seen:
                        seen[b] = m.name

    stats = collections.Counter()
    dropped, unresolved, unresolved_noise = [], [], []
    per_ko = {}
    errors = []

    tf = tarfile.open(mods, 'r:gz') if os.path.exists(mods) else None
    try:
        for b, member_name in seen.items():
            fh = tf.extractfile(member_name) if tf else None
            if fh is None:
                continue
            data = fh.read()
            with tempfile.NamedTemporaryFile(suffix='.ko', delete=False) as t:
                t.write(data); tmp = t.name
            syms, err = undefined_symbols(tmp)
            os.unlink(tmp)
            if err:
                errors.append((b, err))
                continue
            cls = {'builtin': set(), 'module': set(), 'dropped': set(), 'unresolved': set()}
            for s in syms:
                if s not in sym2exp:
                    if NOISE.match(s):
                        unresolved_noise.append((b, s))
                        cls['unresolved'].add(s)
                    else:
                        unresolved.append((b, s))
                        cls['unresolved'].add(s)
                    stats['unresolved'] += 1
                    continue
                exp = sym2exp[s]
                if exp == 'vmlinux':
                    cls['builtin'].add(s); stats['builtin'] += 1
                else:
                    exp_ko = os.path.basename(exp) + '.ko'
                    if exp_ko in kos:
                        cls['module'].add(s); stats['module'] += 1
                    else:
                        fam = DROP_FAM.search(exp)
                        dropped.append((b, s, exp, '六族' if fam else '未在产物集'))
                        cls['dropped'].add(s); stats['dropped'] += 1
            per_ko[b] = {k: sorted(v) for k, v in cls.items()}
    finally:
        if tf:
            tf.close()

    # 汇总报表
    lines = []
    lines.append('==== 符号级隐式依赖对账 ====')
    lines.append(f'产物集 .ko（主表唯一）: {len(kos)}  扫描 .ko（唯一）: {len(seen)}')
    lines.append(f'保留包基准: {len(target_pkgs)} 条')
    lines.append(f'符号引用: 内建导出 builtin={stats["builtin"]}  '
                 f'模块导出 module={stats["module"]}  '
                 f'疑似被剔 dropped={stats["dropped"]}  '
                 f'未解析 unresolved={stats["unresolved"]}（其中噪音 {len(unresolved_noise)}）')
    if errors:
        lines.append(f'读取失败 .ko: {len(errors)}')
        for b, e in errors[:10]:
            lines.append(f'  {b}: {e}')

    lines.append('\n--- dropped（导出方不在产物集，重点排查）---')
    if dropped:
        for ko, sym, exp, tag in sorted(dropped):
            lines.append(f'  {ko}  缺 {sym}  <-  {exp}（{tag}）')
    else:
        lines.append('  无')

    lines.append('\n--- unresolved（symvers 无导出方，人工区分外部库/编译器/真缺）---')
    if unresolved:
        for ko, sym in sorted(unresolved)[:80]:
            lines.append(f'  {ko}  引用 {sym}')
        if len(unresolved) > 80:
            lines.append(f'  …其余 {len(unresolved) - 80} 条见 json')
    else:
        lines.append('  无')

    report = '\n'.join(lines)
    os.makedirs(os.path.join(out, 'audit'), exist_ok=True)
    with open(os.path.join(out, 'audit', 'symbol-audit.txt'), 'w') as f:
        f.write(report + '\n')
    json.dump({
        'stats': dict(stats),
        'scan_ko': len(seen), 'kos': len(kos),
        'dropped': [{'ko': a, 'symbol': b, 'exporter': c, 'tag': d}
                    for a, b, c, d in dropped],
        'unresolved': [{'ko': a, 'symbol': b} for a, b in unresolved],
        'unresolved_noise': [{'ko': a, 'symbol': b} for a, b in unresolved_noise],
        'per_ko': per_ko,
    }, open(os.path.join(out, 'audit', 'symbol-audit.json'), 'w'),
        ensure_ascii=False, indent=1)

    print(report)
    print(f'\n报表: audit/symbol-audit.txt  明细: audit/symbol-audit.json')

    if args.strict and (dropped or unresolved):
        sys.exit(1)


if __name__ == '__main__':
    main()
