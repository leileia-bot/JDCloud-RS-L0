#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kmod-audit.py — 三路采集结果对账（A 源码树 / B 安装树 / C 产物树）。

输入（runner，落表目录 $OUT）：
  audit/ko.A.list   KDIR 内核源码树 .ko 路径清单
  audit/ko.B.list   root-*/lib/modules 安装树 .ko 路径清单
  audit/ko.C.list   staging_dir + bin/targets 产物树 .ko 路径清单
  ko.list           全局 find 汇总（打包用主表）

口径：按 basename 去重；输出各路唯一数、交集与差集，写 audit/ko-audit.txt。
  - B 有 C 无：安装树独立 .ko 没进产物树，疑似丢包，重点排查；
  - 主表有 B 无：全局 find 残留第三方编译目录，不代表交付。
本脚本只对账、不改 .config、不阻断编译。

用法：python3 kmod-audit.py <OUT>
"""
import os, sys


def bases(path):
    s = set()
    if os.path.exists(path):
        for ln in open(path, errors='ignore'):
            ln = ln.strip()
            if ln:
                s.add(os.path.basename(ln))
    return s


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else '.'
    A = bases(os.path.join(out, 'audit/ko.A.list'))
    B = bases(os.path.join(out, 'audit/ko.B.list'))
    C = bases(os.path.join(out, 'audit/ko.C.list'))
    allk = bases(os.path.join(out, 'ko.list'))

    lines = [
        f"A 源码树唯一 .ko: {len(A)}",
        f"B 安装树唯一 .ko: {len(B)}",
        f"C 产物树唯一 .ko: {len(C)}",
        f"主 ko.list 唯一 .ko: {len(allk)}",
        f"B∩A: {len(B & A)}  B∩C: {len(B & C)}  A∩C: {len(A & C)}",
        f"B 有 A 无（安装树未进源码树）: {len(B - A)}  {sorted(B - A)[:20]}",
        f"B 有 C 无（安装树未进产物树，疑似丢包）: {len(B - C)}  {sorted(B - C)[:20]}",
        f"主表有 B 无（全局 find 残留第三方目录）: {len(allk - B)}  {sorted(allk - B)[:20]}",
    ]
    report = '\n'.join(lines)
    os.makedirs(os.path.join(out, 'audit'), exist_ok=True)
    with open(os.path.join(out, 'audit/ko-audit.txt'), 'w') as f:
        f.write(report + '\n')
    print('==== 三路对账 ====')
    print(report)


if __name__ == '__main__':
    main()
