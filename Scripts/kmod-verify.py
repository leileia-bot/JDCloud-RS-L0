#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kmod-verify.py — 目标集合双表（包名层 + 内建/独立模块层）强校验。

流程定位：在 kmod-screen.py 筛选之后跑。筛完把当前实际选中的 kmod / 模块集合，
和仓库固化的基准表做差分对照：
  - 全对 → 放行（退出 0）；
  - 不对 → 报错终止（退出 1），逐条指出 + 多余（不该出现）/ - 缺失（必须要有），
    并尽量给出归属 kmod 包，方便排查。

基准表（Config/ 下，回填前为空则对应层跳过，不阻断编译）：
  target_kmod.txt    包名层：一行一个 kmod-xxx
  target_builtin.txt 内建层：一行一个内核模块名（去 .ko 后缀，对应 =y）
  target_module.txt  独立层：一行一个 .ko 文件名（含后缀，对应 =m）

口径边界：
  - 内建模块编进内核、无独立 .ko，所以 builtin/module 两张表分开核对。
  - 基准表是“标准答案”，脚本不自动增删；要调整清单先改基准表再重编。
  - 包名对上但 ko 没编出来（内核开关关闭）的情况，由 module/builtin 层兜住。

用法（runner，cwd=./wrt）：
  python3 Scripts/kmod-verify.py
环境变量：
  KMOD_CFG=.config  KMOD_MK_GLOB='package/kernel/linux/modules/*.mk'
  KMOD_DIR=Config   （基准表所在目录）
"""
import re, glob, os, sys

CFG = os.environ.get('KMOD_CFG', '.config')
MK_GLOB = os.environ.get('KMOD_MK_GLOB', 'package/kernel/linux/modules/*.mk')
CONF_DIR = os.environ.get('KMOD_DIR', 'Config')

MUST = ['kmod-mac80211', 'kmod-cfg80211', 'kmod-ath11k', 'kmod-ath11k-ahb']


def read_baseline(fname):
    """读基准表，剥注释/空行，返回集合；文件缺失或全注释返回空集（视为待回填）。"""
    path = os.path.join(CONF_DIR, fname)
    if not os.path.exists(path):
        return set()
    out = set()
    for ln in open(path, errors='ignore'):
        ln = ln.strip()
        if ln and not ln.startswith('#'):
            out.add(ln)
    return out


def parse_pkg_ko(files):
    """包名 -> [ko 文件名]（取 FILES 路径 basename）。"""
    pkg_ko = {}
    for f in files:
        txt = open(f, errors='ignore').read()
        for m in re.finditer(r'define KernelPackage/([A-Za-z0-9_.-]+)\n(.*?)\nendef', txt, re.S):
            pkg, body = 'kmod-' + m.group(1), m.group(2)
            kos = []
            for fm in re.finditer(r'FILES:\s*(.*?)(?=\n\s*[A-Z_]+:=\n|\nendef|\Z)', body, re.S):
                for tok in fm.group(1).replace('\\', ' ').split():
                    tok = tok.strip()
                    if tok.endswith('.ko'):
                        kos.append(os.path.basename(tok))
            pkg_ko[pkg] = sorted(set(kos))
    return pkg_ko


def load_selected(cfg):
    sel = {}
    if not os.path.exists(cfg):
        return sel
    for ln in open(cfg, errors='ignore'):
        m = re.match(r'^CONFIG_PACKAGE_([A-Za-z0-9_.+-]+)=([ym])$', ln.strip())
        if m:
            sel[m.group(1)] = m.group(2)
    return sel


def diff(name, baseline, current):
    """返回 (extra, missing)：extra=当前有基准无；missing=基准有当前无。"""
    extra = sorted(current - baseline)
    missing = sorted(baseline - current)
    print(f'--- {name}：基准 {len(baseline)} / 当前 {len(current)}')
    if extra:
        print(f'  + 多余（当前有、基准无）{len(extra)}:')
        for x in extra:
            print(f'    + {x}')
    if missing:
        print(f'  - 缺失（基准有、当前无）{len(missing)}:')
        for x in missing:
            print(f'    - {x}')
    if not extra and not missing:
        print('  ✅ 一致')
    return extra, missing


def main():
    files = sorted(glob.glob(MK_GLOB))
    pkg_ko = parse_pkg_ko(files)
    sel = load_selected(CFG)
    sel_k = {k: v for k, v in sel.items() if k.startswith('kmod-')}

    base_pkg = read_baseline('target_kmod.txt')
    base_builtin = read_baseline('target_builtin.txt')
    base_module = read_baseline('target_module.txt')

    failures = []

    # 命根包断言（与基准无关，必须在）
    bad_must = [m for m in MUST if m not in sel_k]
    if bad_must:
        print(f'失败: 命根包缺失 {bad_must}')
        sys.exit(1)
    print('命根校验通过:', ' '.join(MUST))

    # 包名层
    if base_pkg:
        cur_pkg = set(sel_k)
        extra, missing = diff('包名层 kmod', base_pkg, cur_pkg)
        failures += [(f'pkg:{x}', 'extra') for x in extra]
        failures += [(f'pkg:{x}', 'missing') for x in missing]
    else:
        print('包名层基准 target_kmod.txt 待回填，跳过强校验。')

    # 内建层（=y）：包 -> 模块名（ko 名去 .ko）
    if base_builtin:
        cur_builtin = set()
        pkg_of_builtin = {}
        for pkg, k in sel_k.items():
            if k != 'y':
                continue
            for ko in pkg_ko.get(pkg, []):
                mod = ko[:-3] if ko.endswith('.ko') else ko
                cur_builtin.add(mod)
                pkg_of_builtin.setdefault(mod, pkg)
        extra, missing = diff('内建层 (=y)', base_builtin, cur_builtin)
        for x in extra:
            failures.append((f'builtin:{x} ({pkg_of_builtin.get(x, "?")})', 'extra'))
        for x in missing:
            failures.append((f'builtin:{x}', 'missing'))
    else:
        print('内建层基准 target_builtin.txt 待回填，跳过强校验。')

    # 独立模块层（=m）：包 -> .ko 名
    if base_module:
        cur_module = set()
        pkg_of_module = {}
        for pkg, k in sel_k.items():
            if k != 'm':
                continue
            for ko in pkg_ko.get(pkg, []):
                cur_module.add(ko)
                pkg_of_module.setdefault(ko, pkg)
        extra, missing = diff('独立层 (=m .ko)', base_module, cur_module)
        for x in extra:
            failures.append((f'module:{x} ({pkg_of_module.get(x, "?")})', 'extra'))
        for x in missing:
            failures.append((f'module:{x}', 'missing'))
    else:
        print('独立层基准 target_module.txt 待回填，跳过强校验。')

    if failures:
        print(f'\n校验失败: 共 {len(failures)} 处不一致（+ {sum(t=="extra" for _,t in failures)} / - {sum(t=="missing" for _,t in failures)}）')
        sys.exit(1)

    print('\n校验通过：当前集合与已回填基准全部一致（未回填层已跳过）。')


if __name__ == '__main__':
    main()
