#!/bin/sh
# 体检：看离线源是否接通、每层有多少包、内核模块对不对版本
REPO=""
for m in /mnt/* /tmp/mnt/* /media/*; do
    [ -d "$m/repo" ] && REPO="$m/repo" && break
done

echo "== 1. 仓库位置 =="
if [ -n "$REPO" ]; then echo "  $REPO"; else echo "  未找到！确认 U 盘已挂载且 repo/ 在根目录"; fi

echo "== 2. 当前 apk 源 =="
cat /etc/apk/repositories 2>/dev/null || echo "  （无）"

echo "== 3. 各层包数 =="
for d in "$REPO"/base "$REPO"/libs "$REPO"/luci "$REPO"/packages; do
    [ -d "$d" ] || continue
    printf "  %-28s %s 个\n" "$(basename "$d")" "$(ls "$d"/*.apk 2>/dev/null | wc -l)"
done
for d in "$REPO"/kmods/*; do
    [ -d "$d" ] || continue
    printf "  kmods/%-22s %s 个\n" "$(basename "$d")" "$(ls "$d"/*.apk 2>/dev/null | wc -l)"
done

echo "== 4. 内核版本对照 =="
RUNNING=$(uname -r)
echo "  运行中：$RUNNING"
if [ -n "$REPO" ]; then
    for d in "$REPO"/kmods/*; do
        [ -d "$d" ] || continue
        v=$(basename "$d")
        case "$RUNNING" in
            "$v"*) echo "  匹配：$v" ;;
            *)     echo "  不匹配：$v ← 这层别用，vermagic 对不上" ;;
        esac
    done
fi

echo "== 5. 索引文件 =="
for d in "$REPO"/base "$REPO"/libs "$REPO"/luci "$REPO"/packages; do
    [ -d "$d" ] || continue
    [ -f "$d/packages.adb" ] && echo "  $(basename "$d"): 有" || echo "  $(basename "$d"): 缺 packages.adb（apk update 会报错）"
done
