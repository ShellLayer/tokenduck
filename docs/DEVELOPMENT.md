# 开发与验证

## 环境

Windows 11 x64，Python 3.14 x64，包含 Tkinter。程序运行时只使用标准库；构建工具的固定版本在 `requirements-build.txt`。

```powershell
python tokenduck.py
python -B -m unittest discover -s tests -v
python tokenduck.py --self-check
./build.ps1
```

`build.ps1` 创建 `.build-venv` 并打包为无控制台的单文件 `dist/TokenDuck.exe`，再生成带文档、许可和 SHA-256 的便携 ZIP。不要将 `dist`、`build`、虚拟环境或用户数据提交到 Git。

## 验证范围

离线测试使用合成账号、模拟网络与临时文件，覆盖 Kimi 零用量省略字段、有效窗口与未知状态、额度解析、缓存失效显示、账号绑定、独立续期、加密存储、原子迁移、跨进程保护、请求目标和重定向边界，以及更名后的数据与自启兼容。

`TokenDuck.exe --self-check` 不读取真实账号，不访问账号接口，结果写入所选数据目录的 `self_check.json`。它验证 DPAPI 往返、跨站重定向拒绝、Kimi 满额文字、任务栏文字间距、右键详情完整性、只读菜单行、两个额度选择按钮和原生窗口工具样式。

`python tokenduck.py --once` 在没有其他实例时请求真实额度并打印；打包版的输出保存到数据目录下 `quota_diagnostics.json`。这属于真实账号操作，不是离线测试。日常刷新请使用现有实例的右键菜单。

## 结构

| 路径 | 用途 |
| --- | --- |
| `tokenduck.py` | 平台适配、额度请求、解析、缓存、任务栏界面与设置 |
| `subscription_menu.py` | 订阅详情菜单、重置说明与被动窗口样式 |
| `secure_store.py` | 当前 Windows 用户加密的凭证存储 |
| `codexbar.py` | 更名前源码启动命令的兼容入口 |
| `tests/` | 离线行为与账号保护测试 |
| `TokenDuck.spec` | PyInstaller 打包配置 |
| `tools/collect_licenses.py` | 收集当前构建环境中随发行包分发的许可 |

`subscription_menu_rows` 只接收公开额度字段并生成只读信息行。菜单每次打开时重建信息区域，操作区域保持稳定。任务栏没有鼠标进入、离开或左键动作绑定。交互保护同时检查菜单发布状态、Tk 鼠标抓取、可见子窗口与 [Windows GUI 线程菜单状态](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-guithreadinfo)，有交互时不重绘、修改字体、抬升或移动任务栏窗口，结束后合并处理待刷新的界面。字体布局按任务栏高度、字号和 Tk 缩放缓存，位置未改变时不重复设置几何信息。

需要在现有程序运行时构建候选版本，可使用 `./build.ps1 -OutputDirectory build/candidate`，验证后再替换正在使用的版本。

`python tools/check_menu.py` 使用合成数据和隐藏窗口检查真实 Tk 菜单，包括额度口径、正常与旧读数、只读信息行、重复打开、高缩放文字宽度、按钮选择与保存，以及透明测试对话框打开时对任务栏抬升和移动的抑制。检查不弹出菜单、不调用屏幕捕获接口；GitHub Windows 检查会运行此项验证。

`python tools/check_popup.py` 另外短暂显示一个使用合成数据的真实 Windows 菜单，跨越定时布局与数据刷新回调，记录原生菜单尺寸事件；检测到反复缩小或重排即失败。其菜单操作均为空动作，自动关闭并恢复前台窗口，不读取账号、不捕获屏幕。此项用于覆盖仅检查隐藏控件时遗漏的真实菜单行为。

加密文件头、凭证锁和单实例标记中的旧名称是兼容格式，不能直接替换。旧用户原地复用已有数据目录；新安装使用 TokenDuck 目录，不自动搬移或重新加密账号。

## 发布

先运行离线测试、构建和打包版自检。核对版本号、Windows 文件版本及 ZIP 内容，使用 `SHA256SUMS.txt` 验证可执行文件和 ZIP。

GitHub Actions 在 Windows 上运行测试并验证打包版，提供构建产物。正式 Release 只上传当前版本的 EXE、ZIP 与校验文件，不上传个人配置、日志或凭证。发布可使用 `gh release create`；需要仓库写权限。
