# LumaBLE

面向 Windows 的桌面应用，用于控制 BLE RGB 灯带控制器。

LumaBLE 可以扫描附近受支持的蓝牙灯带控制器、连接设备、调整 RGB 颜色、亮度和电源、
应用内置效果、调整效果速度，并保存可重复使用的灯光配置。它还提供屏幕与音乐同步、
场景、自动化规则、本地 API、诊断以及浅色和深色主题。

作者：`dollza`

版本：`0.3.8 beta`

可在 [Releases 页面](https://github.com/DanKo12345/lumable/releases) 下载最新的 Windows 构建。

如果发现错误，或者控制器无法正常工作，请创建
[Issue](https://github.com/DanKo12345/lumable/issues)。

其他语言：

- [English](README.md)
- [Русский](README.ru.md)
- [Español](README.es.md)

![LumaBLE 颜色和亮度控制](docs/images/lumable-color-dark.png)

## 主要功能

- RGB、亮度、色温和电源控制。
- 场景、快捷模式、控制器效果和应用动画。
- 屏幕同步和音乐同步。
- 按时间、前台应用、空闲时间、LumaBLE 启动或灯带连接触发自动化。
- Pro 电源计划可通过 Windows 在 LumaBLE 关闭时运行。
- 本地 API，可在同一网络中使用手机控制灯光。
- 为不受支持的控制器和 BLE 问题导出诊断信息。
- 键盘导航、减少动态效果和四种界面语言。

## 支持的控制器

- BLEDOM / ELK-BLEDOM 兼容控制器。
- Magic Home / MagicLight BLE 控制器。
- BanlanX SP61x / SP62x BLE 控制器。
- Triones / Happy Lighting 兼容 BLE LED 控制器。

## Windows 安装

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

测试和发布构建工具：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## 启动

```powershell
.\run_app.bat
```

## 测试

```powershell
.\.venv311\Scripts\python.exe -m pytest
```

```powershell
.\.venv311\Scripts\python.exe -m ruff check .
```

## 应用数据

应用数据会通过 `platformdirs` 保存到标准的用户应用数据目录。
在 Windows 上通常是：

```text
%APPDATA%\LumaBLE
```

自定义翻译可以作为 JSON 文件放入：

```text
%APPDATA%\LumaBLE\i18n
```

项目中的 `data/` 文件夹只用于旧版开发配置和设置的首次迁移。
不要将它提交到仓库，也不要放进公开发布的源码压缩包。

## 报告问题

报告错误或不受支持的控制器时，请包含：

- Windows 版本。
- LumaBLE 版本。
- 应用中显示的控制器名称。
- 你尝试执行的操作。
- 实际发生的情况。
- 如果可以，请附上诊断报告。

导出诊断：

1. 打开 LumaBLE。
2. 打开设备诊断。
3. 点击 Copy diagnostics 或 Export diagnostics。
4. 将报告粘贴到 GitHub issue，或附上导出的 `.txt` 文件。
