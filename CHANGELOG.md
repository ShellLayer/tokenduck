# Changelog

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
