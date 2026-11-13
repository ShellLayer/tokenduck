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

`TokenDuck.exe --self-check` 不读取真实账号，不访问账号接口，结果写入所选数据目录的 `self_check.json`。它验证 DPAPI 往返、跨站重定向拒绝、Kimi 满额文字、任务栏文字间距、右键详情完整性、只读菜单行和原生窗口工具样式。

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

`subscription_menu_rows` 只接收公开额度字段并生成只读信息行。菜单每次打开时重建信息区域，操作区域保持稳定。任务栏没有鼠标进入、离开或左键动作绑定。

需要在现有程序运行时构建候选版本，可使用 `./build.ps1 -OutputDirectory build/candidate`，验证后再替换正在使用的版本。

`python tools/check_menu.py` 使用合成数据和隐藏窗口检查真实 Tk 菜单，包括额度口径、正常与旧读数、只读信息行、重复打开和高缩放文字宽度。检查不弹出菜单、不调用屏幕捕获接口；GitHub Windows 检查会运行此项验证。

加密文件头、凭证锁和单实例标记中的旧名称是兼容格式，不能直接替换。旧用户原地复用已有数据目录；新安装使用 TokenDuck 目录，不自动搬移或重新加密账号。

## 发布

先运行离线测试、构建和打包版自检。核对版本号、Windows 文件版本及 ZIP 内容，使用 `SHA256SUMS.txt` 验证可执行文件和 ZIP。

GitHub Actions 在 Windows 上运行测试并验证打包版，提供构建产物。正式 Release 只上传当前版本的 EXE、ZIP 与校验文件，不上传个人配置、日志或凭证。发布可使用 `gh release create`；需要仓库写权限。
