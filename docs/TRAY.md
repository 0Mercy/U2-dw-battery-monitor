# 托盘使用说明

> 公开副本说明：本文中的“本机”指原开发环境。公开仓库不含官方更新器、提取固件、抓包及原始操作日志；标注“仅本地保留”的证据不随仓库发布。校准与快照为脱敏历史样例，详见 [公开范围](../docs/PUBLICATION.md)。

状态：初版，更新于 2026-10-05。主要自动化及实机验收已通过；真实睡眠唤醒尚未进行，详见 [验收报告](ACCEPTANCE-2026-10-05.md)。

## 启动与退出

双击根目录 [Start-U2DW.vbs](../Start-U2DW.vbs)。启动器隐藏控制台，通过 Windows PowerShell 编译并运行 [TrayApp.cs](../tray/TrayApp.cs)。运行时需要 Windows 自带的 .NET Framework WinForms，以及本地 Python；启动器默认从 PATH 查找 `python.exe`。

从根目录手动启动，或指定解释器：

```powershell
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File .\tray\start.ps1

# Python 不在 PATH 时替换为实际解释器路径
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File .\tray\start.ps1 -PythonPath 'C:\Python\python.exe'
```

`ExecutionPolicy Bypass` 仅用于此次 PowerShell 进程，不修改持久执行策略。直接启动命令会占用当前终端；日常使用双击入口。没有安装服务、注册开机启动或更改驱动。

图标位于 Windows 通知区域，可能收在“^”内。右键选择“退出”结束托盘及其读取进程。重复启动由当前会话内命名互斥量拦截，第二个实例直接退出。

## 显示与交互

| 状态 / 操作 | 表现 |
|---|---|
| 估算可用 | 图标显示数字；悬浮和菜单明确显示“约 N%” |
| 电量估算 ≤10% | 图标底部变为橙红色；未实现弹窗提醒 |
| 读取失败、基站缺失、版本未知、校准无效 | 显示灰色 `--`，菜单说明原因 |
| 鼠标悬浮 | 估算、电压、查询时间及缓存年龄未知的提示 |
| 右键“立即刷新”或双击 | 发起一次读取；正在读取时不叠加任务 |
| 定时刷新 | 一轮结束后等待 30 秒，再读取一次 |
| 退出 | 移除图标，停止计时器，结束所属读取进程 |

图标只显示数字以适应通知区域尺寸；“约”的语义保留在悬浮说明与菜单中。电压来自基站缓存，查询时间不等于采样时间；显示“约 100%”不证明当前正在充电或已经充满。模型限制见 [百分比方法](../diagnostics/BATTERY_PERCENTAGE.md)。

## 实现边界

- UI 使用 WinForms `NotifyIcon`，独立 Python 进程负责一次读取。托盘不会在 UI 线程直接等待 HID 响应；单次读取超过 25 秒会结束该子进程并显示未知。
- UI 计时器发现超过 10 秒未处理事件时，会清除旧显示并重新读取，用于覆盖睡眠恢复或长时间停顿。睡眠唤醒的实机验收仍待完成。
- 实时读取复用 `read_live_snapshot()` 和 `interpret_snapshot()`，保留原有命令白名单、版本与响应校验。串行快照由 `device_session()` 锁保护。
- 锁覆盖本项目当前版本的 `query_version.query()`、完整实时快照及 `vendor_listen.listen()`；外部软件不遵守该锁。进行硬件实验前退出托盘，可避免周期查询影响实验窗口。
- 校准沿用本机已保存的参考；无有效校准时托盘显示未知。命令行仍可不带校准文件，仅做分档解释。
- 当前没有独立 EXE、安装器、自动更新或开机启动功能。

## 运行状态与排障

运行时仅保存最新显示状态至 `%LOCALAPPDATA%\U2DWTray\status.json`，含估算、电压、查询时间和进程 ID，不含原始 HID 路径和鼠标动作。正常退出时标记为 `stopped`；进程被外部终止时文件可能保留旧状态，因此排障时同时核对时间及进程是否仍存在。

启动异常保存在同目录的 `startup-error.txt`，其中可能包含本机文件路径。启动时会提示该文件位置。旧错误文件不会因后来启动成功而自动删除，判断时注意修改时间。

出现 `--` 时，右键查看原因：

- “未找到基站”：检查连接，随后立即刷新。
- “设备正由其他诊断程序使用”：结束对应诊断后刷新。
- “校准文件缺失或无效”：确认项目完整，保留 `diagnostics` 中的校准及证据文件。
- “读取失败 / 超时”：确认没有官方更新器或旧版诊断同时读取，等待下一轮。不要以升级固件作为默认排障步骤。

## 资料

实现时于 2026-09-25 核对了微软 [NotifyIcon API](https://learn.microsoft.com/en-us/dotnet/api/system.windows.forms.notifyicon) 和 [互斥量用法](https://learn.microsoft.com/en-us/windows/win32/sync/using-mutex-objects)。这些资料说明所用平台机制；本项目行为是否符合要求以 [验证记录](VALIDATION.md) 为准。
