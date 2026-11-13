# Changelog

## 0.3.6 — 2026-11-13

- Further reduced the hover tooltip's common layout from 320×266 to 260×133 logical pixels.
- Removed the generic heading, routine update timestamp and instruction footer; display mode now sits beside the monthly quota title.
- Condensed plans, expiry dates, monthly counts and Code attribution into short rows, while keeping connection failures and the last successful update visible.
- Kept automatic dismissal, click-through behavior, full-width monthly progress and remaining/used mode.

## 0.3.5 — 2026-11-13

- Replaced the large provider dashboard with a compact supplementary tooltip, centered on Kimi monthly totals, plans, expiry and connection issues.
- Removed pinning and repeated short-term quota bars from the hover view; taskbar quotas remain always visible.
- Added a brief hover delay, automatic dismissal on leaving the taskbar widget, and click-through styling so underlying applications remain usable.
- Reduced typical sample layout from 400×739 to 320×266 logical pixels and retained remaining/used mode, monthly progress and stale-reading metadata.
- Updated regressions and screen-capture-free layout checks for the simplified interaction.

## 0.3.4 — 2026-11-13

- Explained GLM's rolling 5-hour recovery when its API omits a precise timestamp, replacing blank taskbar time slots with full/unused, rolling, or waiting-for-refresh states.
- Kept exact provider timestamps as countdowns and distinguished recovery times from fixed reset times in the flyout.
- Avoided treating a rounded 0% usage as full capacity when available counts indicate consumption.
- Added monitor-response, display, stale-state and native text-spacing regressions without screen capture.

## 0.3.3 — 2026-11-13

- Promoted Kimi's monthly total from a text note to a separate full-width progress bar below the paired short-term windows.
- Grouped count, reset and Kimi Code consumption details with their monthly quota; preserved remaining/used mode and stale-reading behavior.
- Widened the flyout slightly and combined healthy update/expiry metadata into compact card footers.
- Added monthly-meter regressions, packaged checks and real Tk layout validation without screen capture.

## 0.3.2 — 2026-11-13

- Added a persisted remaining/used display setting, applied to taskbar numbers, flyout numbers, bar fill and convertible monthly counts.
- Added taskbar mode markers and kept scarcity colors tied to actual remaining allowance.
- Changed left-click from refreshing to pinning or dismissing the flyout; automatic and right-click refresh remain available.
- Removed repeated foreground lifting from left-click, kept the taskbar widget passive, and reused flyout widgets when content is unchanged.
- Added a close control, mode and pin regressions, and packaged checks for consistent used-mode rendering.

## 0.3.1 — 2026-11-13

- Replaced the plain text tooltip with themed provider cards, paired quota bars, plan details, reset times and update status.
- Kept monthly balances and expiry details visible; failed readings remain muted and explicitly marked as previous records.
- Added a short hover delay, pointer transfer into the flyout, in-place refresh and scrolling within monitor bounds.
- Kept the flyout out of the taskbar and Alt+Tab, without stealing keyboard focus.
- Added synthetic hover previews, placement regressions and packaged flyout checks.

## 0.3.0 — 2026-11-13

First public release as **TokenDuck**.

- Renamed the application, launchers, Windows package and documentation.
- Preserved existing encrypted sessions, settings, startup entries and cross-version single-instance protection.
- Kept Codex, Kimi and GLM / ZCode quotas always visible without a separate taskbar button.
- Included the Kimi full-quota display fix, quota cache status, current-user credential encryption and explicit account binding.
- Added MIT licensing, English introduction, privacy documentation, contribution guidance and Windows CI.
