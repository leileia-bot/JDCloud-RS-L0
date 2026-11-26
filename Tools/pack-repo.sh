#!/bin/sh
# 把编译产物里的 .apk 分类成 U 盘仓库结构
# 用法：pack-repo.sh <apk所在目录> <输出根目录> [kmod版本子目录名]
set -e
SRC="$1"; OUT="$2"; VER="$3"
[ -n "$SRC" ] && [ -n "$OUT" ] || { echo "用法: $0 <apk目录> <输出目录> [ver]"; exit 1; }
VER="${VER:-unknown}"

mkdir -p "$OUT/base" "$OUT/libs" "$OUT/luci" "$OUT/packages" "$OUT/kmods/$VER"

for f in "$SRC"/*.apk; do
    [ -f "$f" ] || continue
    n=$(basename "$f")
    case "$n" in
        kmod-*|nss-*|qca-*)                 d="$OUT/kmods/$VER" ;;
        luci-*)                             d="$OUT/luci" ;;
        lib*|*-libs|ca-bundle*|*-openssl*)  d="$OUT/libs" ;;
        base-files*|busybox*|dropbear*|uhttpd*|procd*|netifd*|ubus*) d="$OUT/base" ;;
        *)                                  d="$OUT/packages" ;;
    esac
    mv -f "$f" "$d/"
done

# 每层生成索引（apk-tools 3.x 的 packages.adb）
for d in "$OUT"/base "$OUT"/libs "$OUT"/luci "$OUT"/packages "$OUT"/kmods/"$VER"; do
    [ -d "$d" ] || continue
    ( cd "$d" && ls *.apk >/dev/null 2>&1 && apk mkndx -o packages.adb *.apk ) 2>/dev/null \
        || echo "  !! $d 缺 apk mkndx，索引未生成"
done

echo "== 分类结果 =="
for d in "$OUT"/base "$OUT"/libs "$OUT"/luci "$OUT"/packages "$OUT"/kmods/"$VER"; do
    [ -d "$d" ] && printf "%-40s %s\n" "${d#$OUT/}" "$(ls "$d"/*.apk 2>/dev/null | wc -l)"
done
