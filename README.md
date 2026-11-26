# JDCloud-RS-L0

京东云亚瑟 AX1800 Pro（qualcommax / ipq60xx / `jdcloud_re-ss-01`）的**底座固件**仓库。

只做 L0：内核 + 网络 + LuCI（vantage 主题）+ U盘存储层。插件（daede / OpenClash 等）后续作为独立 ipk 走 U 盘离线仓库安装，不塞进这个固件。

## 已定栈（只留一条路线）

| 项 | 选择 |
|---|---|
| 源码 | VIKINGYFY/immortalwrt `owrt`（非 NSS） |
| 加速 | 纯软件，`qca-nss-*` 全关 |
| 防火墙 | nftables / fw4（不用 iptables-legacy） |
| DNS | dnsmasq-full（独占 53） |
| 主题 | luci-theme-vantage |
| U盘 | ext4 + vfat（砍 exfat / ntfs3） |
| 分区 | 内核槽 12M、根分区 2048M |
| ZRAM | zram-swap（默认内存一半） |

## 构建

Actions → `L0-BASE` → Run workflow。

- `TEST=true`：只生成 `.config` 并打印冲突检查，不编译
- `TEST=false`：全量编译，产物进 Release（`sysupgrade.bin` / `factory.bin` / `.manifest` / `Config-*.txt`）

## 结构

```
.github/workflows/L0-BASE.yml   构建流
Config/L0-AX1800.txt            配置片段
files/                          打包进固件的文件（uci-defaults 等）
```
