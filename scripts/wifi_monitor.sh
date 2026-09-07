#!/usr/bin/env bash
# 监控 WiFi Direct 链路状态：记录 P2P 会话期间的速率/频宽/信号
# 用法: 先启动 GUI 开始监听 → 运行本脚本 → 手机传大文件 → 传输结束 Ctrl+C
# 输出写到 /tmp/wifi_monitor.log
DEV="wlp9s0"
OUT="/tmp/wifi_monitor.log"

echo "=== WiFi Direct 链路监控开始 $(date +%T) ===" | tee "$OUT"

for i in $(seq 1 600); do
  # 只在连到 DIRECT 网络时记录（非 DiffRobot_5G）
  LINK=$(iw dev $DEV link 2>/dev/null)
  SSID=$(echo "$LINK" | grep -i ssid)
  if echo "$SSID" | grep -qi "DIRECT"; then
    echo "--- $(date +%T.%3N) ---" >> "$OUT"
    echo "$LINK" | grep -E "SSID|freq|signal|rx bitrate|tx bitrate" >> "$OUT"
    # station dump 里的实时速率和信号
    iw dev $DEV station dump 2>/dev/null | grep -E "signal:|tx bitrate|rx bitrate" >> "$OUT"
    # 每秒累计流量（判断是否在传输）
    RX1=$(cat /sys/class/net/$DEV/statistics/rx_bytes)
    TX1=$(cat /sys/class/net/$DEV/statistics/tx_bytes)
    sleep 2
    RX2=$(cat /sys/class/net/$DEV/statistics/rx_bytes)
    TX2=$(cat /sys/class/net/$DEV/statistics/tx_bytes)
    echo "  速率: 收 $(( (RX2-RX1)/2/1024/1024 )) MB/s 发 $(( (TX2-TX1)/2/1024/1024 )) MB/s" >> "$OUT"
  fi
  sleep 2
done
