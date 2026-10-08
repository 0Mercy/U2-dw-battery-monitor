# 验收工具

> 公开副本说明：本文中的“本机”指原开发环境。公开仓库不含官方更新器、提取固件、抓包及原始操作日志；标注“仅本地保留”的证据不随仓库发布。校准与快照为脱敏历史样例，详见 [公开范围](../docs/PUBLICATION.md)。

这些工具只有在用户要求测试或验收时运行。输出放入新的 `diagnostics/acceptance-日期时间/`，保留旧记录。没有安装额外测试框架。

## 自动化回归

从项目根目录运行：

```powershell
$env:PYTHONIOENCODING = 'utf-8'
$runPath = Join-Path (Get-Location).Path ('diagnostics\acceptance-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $runPath | Out-Null

# Python 算法、校准、响应解析与实际 Windows 命名互斥；HID I/O 被替换
python -B tests/test_battery.py (Join-Path $runPath 'python.json')

# C# 托盘组件；使用隔离状态目录和假的读取进程，不访问硬件
powershell.exe -NoProfile -STA -File tests/run-tray-components.ps1 -OutDir $runPath
```

Python 回归使用标准库 `unittest`，覆盖 30 个测试方法，其中部分包含多组输入。命名互斥测试会短暂占用真实项目互斥量，因此独立回归前宜退出托盘，避免偶然与它的查询冲突。

C# 回归编译生产源码及验收类，使用内部构造入口指定隔离目录并隐藏测试图标。假的 Python 读取器不导入任何 HID 模块。它会真实等待 25 秒超时，以确认子进程被清理；总运行约 30–40 秒。检查 `tray-components.json` 每项 `passed` 字段，不能只看 PowerShell 进程退出码。该测试不等于任务栏视觉或鼠标实际操作验收。

## 实机观察

`observe-tray.ps1 -OutFile <新的JSONL路径> -Seconds 1200` 每 2 秒读取托盘状态文件及该进程的 CPU、内存和句柄数；它本身不发送设备查询。先启动托盘和观察器，确认记录存在后，再请用户关开鼠标、拔插基站或睡眠唤醒。每一步单独确认，保存用户原话与收到确认的时间；不能将确认时间当作物理操作时间。

观察器最长运行到指定时限。提前结束时只停止本次创建的观察器进程，保留 JSONL；其余托盘和诊断进程分别管理。

专项结果、修复与实机确认统一汇总到 [验证记录](../docs/VALIDATION.md)。
