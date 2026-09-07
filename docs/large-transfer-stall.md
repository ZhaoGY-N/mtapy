# 大文件传输中途停滞的诊断记录

> 日期：2026-09-07
> 硬件：Ubuntu 20.04 / 内核 5.15.0-139 / MediaTek MT7921e (`14c3:0616`)
> 软件：mtapy Linux 接收端（BlueZ + wpa_supplicant fast path）

## 问题现象

从小米手机（REDMI K90 Pro Max）通过**互传 App** 接收大文件时，传输在
~300–500 MB 处**完全停滞**：

- 无报错、无超时异常，`read()` 永久阻塞
- WiFi 链路不断开（无 deauth/disassoc 记录）
- 速度约 14–24 MB/s（异常偏慢）
- 小文件（≤212 MB）正常
- **手机间传输、小米互联服务均正常**

## 排查过程

### 1. 排除应用层问题

完整握手、WebSocket、流式下载代码均正常——同样代码收到 45MB / 212MB /
7MB 文件都完整。GUI worker 卡住无报错，加文件日志定位到**下载卡在 read
阻塞**。

### 2. 排除手机端 App 问题

反编译小米互传 APK（jadx）确认：
- 大文件「发送失败」是手机 App 用 Netty `HttpChunkedInput` 服务完就关
  channel，status 送不到——但**这是传输完成后**，非中途停滞
- 无 >30s 的传输超时（只有 10s/30s 连接阶段超时）

### 3. WiFi 链路监控（关键数据）

`scripts/wifi_monitor.sh` 在 P2P 传输期间记录：

```
协商速率：413–720 MBit/s（RX，40/80MHz 抖动）
实际吞吐：14–24 MB/s（约协商值的 1/3 到 1/20）
信号：-38 到 -49 dBm（良好）
~300MB 后手机停发数据，链路保持
```

### 4. 对照测试：FTP 走普通 WiFi（非 P2P）

手机开 FTP 服务（经同一 WiFi 网络，非 WiFi Direct），下载同一个 5.2GB
文件：

```
速度：~2.8 MB/s（单连接，较慢）
结果：稳定越过 300MB+（537MB+ 未停滞），持续下载
```

## 结论（当前假设，未定论）

**不是简单的「网卡收 N MB 就死」的驱动 bug**——低速 FTP 不停滞。

两个未决的假设：

1. **高速触发假设**：停滞与传输速率相关。P2P 高速（14–24 MB/s）触发，
   FTP 低速（2.8 MB/s）不触发。可能涉及网卡/固件在**高速连续接收**时的
   DMA/缓冲问题。

2. **P2P 模式专属假设**：WiFi Direct client 模式的驱动路径有别于普通
   AP 模式，P2P 专属 bug。但 FTP 测试速度太低，未能完全排除假设 1。

## 参考线索

- 内核 Bugzilla [221922](https://bugzilla.kernel.org/show_bug.cgi?id=221922)：
  `mt7921e (MT7922): bulk TX transfers stall mid-transfer` —— 高度相似
  但偏 TX 方向；我们主要是 RX
- MT7921/MT7922 Linux 慢速问题（mac80211 MCS 校验等）在社区有多个修复，
  通常需内核 ≥6.x
- 本机内核 5.15 较旧，MT7921 驱动在此版本问题较多

## 后续可行的验证/修复方向

1. **提速 FTP 对照**：手机 FTP 服务端若能多连接/HTTP，在普通 WiFi 下跑
   出 P2P 同级（>14 MB/s）速度，验证「高速触发」假设是否成立。
2. **P2P 限速实验**：强制 P2P 链路低速（如限定 40MHz / 低 MCS），看
   P2P 是否就不停滞——若成立说明速率相关，可用限速规避。
3. **升级内核到 6.x**：MT7921 驱动在 6.x 有大量修复，最可能根治。需重启，
   办公机需谨慎。
4. **接受现状**：超大文件（>300MB）不可靠，作为已知限制记录。

## 诊断工具

- `scripts/wifi_monitor.sh`：监控 WiFi Direct 链路状态和实时吞吐
- GUI worker 文件日志：`/tmp/mtapy_gui.log`（含下载进度）
