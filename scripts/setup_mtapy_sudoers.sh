#!/usr/bin/env bash
# mtapy WiFi 快速连接（wpa_supplicant）所需的 sudoers 配置
# 运行：sudo bash scripts/setup_mtapy_sudoers.sh
#
# 只授予 wpa_supplicant / wpa_cli / dhclient 三个命令的免密 sudo。
# 不使用 pkill（其 -f 可终止任意进程，风险过大）——清理 wpa_supplicant
# 统一走 wpa_cli terminate，精确且安全。
set -e

USER="${SUDO_USER:-$(whoami)}"
SUDOERS_FILE="/etc/sudoers.d/mtapy-wifi"

for tool in /usr/sbin/wpa_supplicant /usr/sbin/dhclient /usr/sbin/wpa_cli /usr/bin/mkdir; do
  [ -x "$tool" ] || { echo "工具不存在: $tool"; exit 1; }
done

echo "${USER} ALL=(root) NOPASSWD: /usr/sbin/wpa_supplicant, /usr/sbin/dhclient, /usr/sbin/wpa_cli, /usr/bin/mkdir" > /tmp/mtapy-wifi-sudoers
chmod 440 /tmp/mtapy-wifi-sudoers
visudo -cf /tmp/mtapy-wifi-sudoers
mv /tmp/mtapy-wifi-sudoers "${SUDOERS_FILE}"
chmod 440 "${SUDOERS_FILE}"

echo "sudoers 配置完成: ${SUDOERS_FILE} (用户: ${USER})"
echo "已授权: wpa_supplicant, dhclient, wpa_cli, mkdir"
