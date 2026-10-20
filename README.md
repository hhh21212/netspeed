# 实时网速悬浮窗

TrafficMonitor 风格的 Windows 网速监控小工具：置顶悬浮窗实时显示下载/上传速度，并常驻系统托盘。

## 运行

1. 安装依赖（首次）：
   ```
   pip install psutil pystray
   ```
2. 双击 `run.bat`（或命令行执行 `pythonw netspeed.py`）启动。

## 使用

- **拖动**：按住窗口任意位置，拖到想要的位置。
- **右键菜单**：置顶开关、单位切换（Mbps / MB/s）、透明度、隐藏、退出。
- **托盘图标**：双击或点「显示/隐藏」切换窗口；「退出」彻底关闭。
- 窗口位置、单位、透明度、置顶状态会自动保存到 `config.json`，重启后恢复。

## 说明

- 网速 = 汇总系统所有非回环/非虚拟网卡的流量，每秒刷新一次，并做了平滑处理（蓝色曲线为下载、橙色为上传）。
- 若数值不符（如计入了虚拟机流量），可编辑 `netspeed.py` 顶部 `IGNORE_KEYWORDS` 列表。
- 若托盘未出现，多为 pystray 未安装：`pip install pystray`。

## 开机自启（可选）

按 `Win + R` 输入 `shell:startup` 回车，把 `run.bat` 的快捷方式放进打开的文件夹即可。

## 打包成 exe（可选）

双击 `build_exe.bat`，生成 `dist\NetSpeed.exe`，可分发、无需 Python 环境。
