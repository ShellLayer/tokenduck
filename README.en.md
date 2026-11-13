# TokenDuck 🦆

**Always-visible AI subscription quotas in your Windows taskbar.**

[Download for Windows](https://github.com/ShellLayer/tokenduck/releases/latest) · [中文](README.md)

TokenDuck keeps **Codex, Kimi, and GLM Coding Plan / ZCode** quotas and reset countdowns visible together. Choose remaining or used allowance across the taskbar and context menu. No click is needed to reveal quotas. The main widget has no separate taskbar button or Alt+Tab entry.

![Illustrative preview with sample values](assets/preview.svg)

*Illustration with sample data; actual appearance varies with theme, scaling and settings.*

## Get started

1. Download `TokenDuck-VERSION-windows.zip` from [Releases](https://github.com/ShellLayer/tokenduck/releases/latest).
2. Extract it to a permanent folder and run `TokenDuck.exe`. Python and administrator rights are not required.
3. Right-click the widget and choose **账户与登录…** (Accounts & login). Use **开机启动** to enable startup.

The current UI is primarily Chinese. Tested on **Windows 11 x64**. Windows 10, other architectures, vertical taskbars and multi-monitor combinations have not been fully validated. Binaries are currently unsigned; SHA-256 checksums are provided with each release.

Right-click the taskbar widget to see subscription details, with Kimi monthly totals first, followed by plans, expiry and connection issues. The widget has no hover popup or left-click action. The same menu provides manual refresh, account, display and startup settings.

The default is **remaining** allowance. Choose the **剩余额度** (remaining) or **已用额度** (used) button in **显示与刷新设置…**. Percentages, bar fill and convertible allowance counts change together. Taskbar labels contain only provider names; settings and subscription details identify the selected mode. Unused Kimi windows display `100%` remaining or `0%` used. Failed refreshes keep the last reading muted and marked `*`; low-allowance colors always reflect actual remaining capacity. Healthy bars use Codex green, Kimi blue and GLM purple, matching the illustration; colors adapt to light/dark themes, turn orange at 25% remaining and red at 10%.

Short-term quota bars remain visible in the taskbar. Supplementary details appear as read-only rows above the actions in the right-click menu, using the current readings each time the menu opens.

Kimi monthly percentages, counts and reset times follow the selected remaining/used mode. Code consumption remains an attribution within the monthly total. Failed refreshes keep the last reading and show the failure reason and last successful update in the menu. Codex expiry comes from the matching account, user and plan in the official local login snapshot, and is labeled accordingly. Missing or past snapshot dates show unknown or waiting-for-update states.

GLM's 5-hour quota recovers dynamically. If the API omits the next recovery time, the taskbar shows **已满** (full), **未用** (unused in used mode), or **滚动** (rolling recovery). Stale readings without a precise time show **待刷新**. A recovery countdown is shown only when an exact timestamp is supplied.

## Account connections

| Service | Connection |
| --- | --- |
| Codex / ChatGPT | Read the official local Codex login; invoke the official login flow when requested |
| Kimi | Prefer the desktop login and attempt to create an independent session; optional browser connection or an existing Kimi Code key |
| GLM Coding Plan / ZCode | Read local ZCode plan credentials or use an existing BigModel / Z.ai plan key |

TokenDuck does not collect passwords or add a telemetry backend. Its own saved credentials are encrypted with Windows current-user DPAPI. It does not refresh the official Codex client's tokens or consume a borrowed Kimi refresh token. Browser import is disabled by default. Switching a bound Kimi account requires an explicit action and successful quota validation. See [privacy details](docs/PRIVACY.md) (Chinese).

This project is independent of the providers. Quota endpoints and local client formats may change. Subscription quotas are not API billing balances or universal token counts.

## Develop

Runtime dependencies are Python's standard library, including Tkinter. Python 3.14 x64 is recommended; development was validated with Python 3.14.10.

```powershell
python tokenduck.py
python -B -m unittest discover -s tests -v
python tokenduck.py --self-check
./build.ps1
```

Tests use synthetic accounts and temporary files. The build script outputs the executable, portable ZIP, checksums and license texts. See [development notes](docs/DEVELOPMENT.md).

Existing pre-TokenDuck users keep their previous data directory and startup entry; fresh installs use `%APPDATA%\tokenduck`. No credential copy is needed during the rename.

[Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [MIT License](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md)
