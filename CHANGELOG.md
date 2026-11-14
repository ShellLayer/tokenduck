# Changelog

## 0.4.2 — 2026-11-14

- Removed the separate rounded shading from the default taskbar appearance. Provider labels, quota text and progress bars now appear directly over the taskbar; updated the illustration to match.
- Kept the full quota area available for right-click through a nearly invisible, passive input child beneath the color-keyed display, including gaps between glyphs and bars. Both children share taskbar placement and recreation cleanup.
- Extended native checks to verify an unchanged blank background pixel, input targeting without shading and visibility across taskbar raises. Kept the existing menu, dialog and exact-quota checks.

## 0.4.1 — 2026-11-14

- Restored GLM / ZCode 5-hour and weekly quota counts in the context menu, alongside percentages and plan details. Counts show complete values with thousands separators and follow remaining/used mode.
- Preserved explicit monitor usage counts and derive missing remaining/used counts only from exact totals and the other count, never from rounded percentages. GLM monthly fallback counts also use full values.
- Added exact-count regressions and packaged self-check coverage, plus a visible settings/accounts interaction check spanning timers, background updates, selection and saving. The check also exercises startup before the taskbar becomes available.

## 0.4.0 — 2026-11-14

- Replaced the independent topmost quota window with a native layered child created directly inside the Windows taskbar. Raising the taskbar now raises the meter with it, without a hide-and-recover cycle.
- Removed the production WinEvent stacking listener and 50 ms recovery poll. Native painting uses a committed GDI snapshot and double buffering; native callbacks never enter Tk/Tcl.
- Routed background request completions through a main-thread queue. Kept the transparent Tk control engine alive when the native display is recreated after host loss.
- Running the portable executable again opens the existing instance's account manager; automatic startup remains silent. Added startup error reporting and fatal-exit stack logging.
- Added native parent/visibility, display recreation, UI-thread dispatch and stress checks while preserving quota parsing, account encryption, menu stability and provider colors.

## 0.3.10 — 2026-11-14

- This release was moved to prerelease after local abnormal exits were observed; use 0.4.0 or later.
- Reduced the roughly one-second disappearance after taskbar clicks: Windows raised the taskbar above the still-visible widget, which previously waited for the next one-second anchor tick.
- Added passive, conditional stacking recovery from foreground/taskbar activity, with a lightweight 50 ms fallback for silent reorders. Recovery never activates the widget, changes its geometry or fetches quotas.
- Preserved interaction guards and the native-menu font-layout fix; event hooks and pending checks are released on exit.
- Added native recovery timing and foreground-preservation checks, including the fallback path without activation events.

## 0.3.9 — 2026-11-13

- Fixed the reproduced native-menu flicker: periodic taskbar font changes caused the posted Windows menu to repeatedly collapse and resize. Pause all painting during interaction, cache font layout, and apply pending updates after closing.
- Added a real posted-menu regression across timer and data-refresh callbacks, using native window events without screen capture.
- Restored distinct Codex green, Kimi blue and GLM purple progress bars matching the repository illustration, with darker light-theme variants, orange at 25% remaining and red at 10% remaining.
- Removed remaining/used suffixes from taskbar provider names; the selected mode stays visible in settings and subscription details.

## 0.3.8 — 2026-11-13

- Stopped repeated taskbar lifts and geometry changes from competing with menus, popdowns and settings dialogs; removed delayed post-click raises.
- Replaced the quota-display dropdown with two mutually exclusive buttons for remaining and used allowance.
- Added Codex subscription expiry from the matching account/user/plan in the official local login snapshot. The date is labeled with its source; past snapshots show "waiting for update", and missing dates remain unknown.
- Kept only the public expiry timestamp in the quota cache and retained read-only access to Codex login files.
- Added menu/dialog stability regressions and real Tk checks for button selection, persistence and suppression of taskbar raises during dialog interaction.

## 0.3.7 — 2026-11-13

- Removed the hover window and all automatic hover and left-click actions.
- Moved monthly totals, counts, reset times, Code attribution, plans, credits, expiry and connection issues into read-only context-menu rows.
- Put Kimi totals first and refresh the details from current data whenever the menu opens, while preserving the existing management actions.
- Retained always-visible taskbar quotas, remaining/used mode, last-success information and passive taskbar window behavior.
- Replaced hover previews and checks with subscription-menu regressions and hidden-window checks that do not post menus or capture the screen.

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
