# U2-DW 电量接口调查

> 公开副本说明：本文中的“本机”指原开发环境。公开仓库不含官方更新器、提取固件、抓包及原始操作日志；标注“仅本地保留”的证据不随仓库发布。校准与快照为脱敏历史样例，详见 [公开范围](../docs/PUBLICATION.md)。

[项目入口](../README.md) · [当前阶段与计划](../docs/PROJECT.md) · [验证与已知问题](../docs/VALIDATION.md)

## 当前结论

2026-09-25，通过用户提供的官方更新器及固件，已找到可用的查询方式：**成功读取接收器版本 8511、鼠标版本缓存 2526，以及电压相关原始值 386、388、387（推断约 3.86、3.88、3.87 V）**。用户关机、开机对照中，版本缓存出现 `2526 → 0000 → 2526`，电压则在重新开机后从 388 变为 387，证实缓存会更新、断连时仍保留旧电压。尚未取得剩余容量百分比，正常使用时的刷新周期、睡眠及充电状态仍未确认。详见 [协议分析与实机结果](PROTOCOL.md)。

以下是此前普通 HID 读取与被动监听的历史记录；其中“没有数据”的结论只针对当时的方法。

**百分比估算已可用：** 固件提供约 10%、25%、50% 的电量灯分档阈值；用户确认满电并取下后，已采集本机约 4.14V 的满电参考。`python diagnostics/battery_percentage.py --live --calibration diagnostics/full-battery-calibration.json` 可单次读取并输出“约 100%”等估算值。已实机运行，尚未测定全程放电误差；详见 [百分比判断方法与证据](BATTERY_PERCENTAGE.md)。

## 已确认的证据

- 设备：`VID_04A5 / PID_800A`，产品名 `BenQ ZOWIE Gaming Mouse`。
- 本次连接位置：USBPcap 总线 4，USB 设备地址 1。重连后需要重新确认；Windows PnP 的 Address 属性不能直接当作抓包设备地址。
- Raw Input 监听记录了来自该设备的 974 次事件，见 `raw-input-motion.json`。
- `query-capture.pcap` 包含 5,428 条记录，其中 2,713 条是端点 `0x81` 返回的 6 字节普通鼠标数据，另有对应的提交记录。
- HID 描述信息显示两个厂商集合：`FF03` 输出 Report ID `8`，`FF04` 输入 Report ID `9`。Windows 报告缓冲区长度均为 16 字节；未发现 Feature 报告。
- 使用正确 Report ID `9` 调用 `HidD_GetInputReport`，Win32 返回错误 31。
- USB 抓包确认该请求已送到接收器：`a1 01 09 01 01 00 10 00`，即接口 1 的 `GET_REPORT(Input, ID 9, length 16)`。
- 接收器返回 `USBD_STATUS_STALL_PID (0xC0000004)`，没有数据。这表示该请求被端点拒绝，不能等同于“电量为零”或“所有电量读取方式都不支持”。
- 在早期调查时，Report ID `8` 的用途尚未知，未发送猜测命令。后续已从官方更新器确认它承载三个只读查询，见 [协议](PROTOCOL.md)。

## 90 秒被动监听结果

- 本机时间 2026-09-25 01:48:12 至 01:49:42，`vendor-charging.json` 显示厂商输入集合成功打开，读取挂起并等待，最终收到 **0 条报告**，无读取异常。
- 同时抓取的 `charging-capture.pcap` 包含 14,281 条普通鼠标返回数据及对应提交记录，没有厂商输入端点的数据返回。
- 抓包和 HID 监听均已自动结束。用户随后确认已完成放上基站充电、取下操作，灯为“两格常亮、第三格闪亮”。操作的精确时间没有单独记录；本轮窗口内没有捕获到厂商报告，不能排除其他状态或查询命令能够取得电量。
- 旧枚举抓包的配置描述符显示：接口 0 是鼠标，输入端点 `0x81`；接口 1 是厂商 HID，输入端点 `0x82`、输出端点 `0x03`。两个 HID 报告描述符长度分别为 66 和 48 字节。这里只解析了配置描述符，没有取得原始报告描述符。

## 工具

以下枚举、监听和抓包工具使用 Python 标准库及 Windows API，无需额外 Python 包；USB 抓包另需 USBPcap 驱动和管理员权限。静态分析与固件模拟另用 `diagnostics/_analysis_deps` 中的 pefile、capstone、Unicorn，不属于日常电量读取依赖。

命令从项目根目录执行。下列实验命令为方法示例：输出采用新的文件名，实际重复采集时继续换名，以免覆盖证据。USB 总线和地址必须重新确认。

```powershell
# 读取 HID 能力信息
python diagnostics/hid_probe.py --out diagnostics/hid-inventory-new.json

# 统计真实鼠标输入，期间手动移动鼠标
python diagnostics/hid_probe.py --listen 30 --out diagnostics/raw-input-motion-new.json

# 被动等待厂商输入报告，不发送厂商输出命令
python diagnostics/vendor_listen.py --seconds 90 --out diagnostics/vendor-charging-new.json

# USBPcap 抓包：仅在管理员终端运行；先确认 bus/address 仍匹配该鼠标
python diagnostics/usb_capture.py --bus 4 --address 1 --seconds 30 --out diagnostics/capture-new.pcap

# 汇总抓包
python diagnostics/pcap_summary.py diagnostics/capture-new.pcap diagnostics/capture-summary-new.json
```

`hid_probe.py --query` 会执行标准 HID GET_REPORT 读取。这个请求在当前设备上已经被证实返回 STALL，无需持续重试。

USBPcap 抓包需要管理员权限，工具到时自动停止并释放句柄。抓包会包含鼠标动作原始数据；Raw Input 统计只保存事件次数。

## 后续证据要求

厂商读取协议和本机初版校准现已完成，详见 [协议](PROTOCOL.md) 与 [百分比方法](BATTERY_PERCENTAGE.md)。后续重点是正常使用时的缓存刷新、睡眠唤醒、完整放电误差和托盘交互。现有接口不能识别充电状态；初版应明确呈现估算与未知状态，验收要求统一维护在 [验证文档](../docs/VALIDATION.md)。

Rapoo 项目的 UI 和托盘设计可以参考，但其厂商命令及电量字节布局不能直接用于卓威。

## 参考

- [Microsoft：USB STALL 状态码说明](https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/case-study--troubleshooting-an-unknown-usb-device-by-using-etw-and-netmon)
- [Microsoft：HIDP_VALUE_CAPS](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/hidpi/ns-hidpi-_hidp_value_caps)
- [USBPcap 源码](https://github.com/desowin/usbpcap)
- [rapoo-tray](https://github.com/Iris-0109/rapoo-tray)
