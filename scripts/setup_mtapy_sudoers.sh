#!/usr/bin/env bash
# mtapy WiFi 快速连接（wpa_supplicant）所需的 sudoers 配置
# 运行：sudo bash /tmp/setup_mtapy_sudoers.sh
set -e

USER="${SUDO_USER:-$(whoami)}"
SUDOERS_FILE="/etc/sudoers.d/mtapy-wifi"

for tool in /usr/sbin/wpa_supplicant /usr/sbin/dhclient /usr/sbin/wpa_cli /usr/bin/pkill; do
  [ -x "$tool" ] || { echo "工具不存在: $tool"; exit 1; }
done

echo "${USER} ALL=(root) NOPASSWD: /usr/sbin/wpa_supplicant, /usr/sbin/dhclient, /usr/sbin/wpa_cli, /usr/bin/pkill" > /tmp/mtapy-wifi-sudoers
chmod 440 /tmp/mtapy-wifi-sudoers
visudo -cf /tmp/mtapy-wifi-sudoers
mv /tmp/mtapy-wifi-sudoers "${SUDOERS_FILE}"
chmod 440 "${SUDOERS_FILE}"

echo "sudoers 配置完成: ${SUDOERS_FILE} (用户: ${USER})"
