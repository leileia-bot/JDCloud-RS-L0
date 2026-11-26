#!/bin/sh
# 一次性把 U 盘离线源能力装进路由器（只装机制，不装插件）
# 用法：把本文件传进路由器（或直接粘贴执行），然后 sh install-usbrepo.sh
set -e

DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo /tmp)"
SRC="$DIR/20-usb-repo"
DST=/etc/hotplug.d/block/20-usb-repo

if [ ! -f "$SRC" ]; then
    echo "找不到 20-usb-repo，请把它和本脚本放同一个目录"; exit 1
fi

mkdir -p /etc/hotplug.d/block
cp -f "$SRC" "$DST"
chmod 755 "$DST"
mkdir -p /mnt/repo

echo "已安装：$DST"
echo
echo "下一步（U 盘侧，电脑上做也行）："
echo "  1. 把 repo/ 解压到 U 盘根目录"
echo "  2. 插到路由器，等 3 秒"
echo "  3. 检查：cat /etc/apk/repositories"
echo
echo "注意：本脚本不安装任何插件。装包需要你自己执行 apk add。"
