# Inventory — /settings, /settings/connections, /admin, /admin/analytics, pre-shell flows, app chrome, UI primitives

Paths relative to `frontend/src/`. Personas (`e2e/support/stack.ts`): `rich-user-active`, `rich-user-new` (onboarding_completed=false), `rich-user-admin`, `rich-user-second`; sign in via `mintStorageState` (`e2e/support/session.ts`). localStorage: `sapling_layout`, `sapling_sidenav_collapsed=1`, `sapling_onboarding_draft` (JSON incl. `step`), `sapling_disclaimer_ack`, `sapling_last_feedback`, `sapling_last_session_feedback`. Mobile < 768px.

## /settings (`components/screens/Settings.tsx`) — tabs `settings-tab-{profile|cosmetics|preferences|notifications|data}`
| State id | What the user sees | Trigger | File:line | testids |
|---|---|---|---|---|
| settings/loading | SettingsFormSkeleton + tab rail | delay settings GET | :320 | – |
| settings/load-error | skeleton forever (console only) | 500 | :144 | – |
| settings/saving-chip | "saving…" chip | save in flight | :308 | – |
| settings/profile | avatar card + Change avatar; @Username, Display name, Bio, Location, Website; Sign out | default | :321-441 | – |
| settings/profile-avatar-uploading / -error | "Uploading…" / revert + toast | avatar POST | :192-231, 342 | – |
| settings/profile-username-checking / -available / -taken / -invalid | "Checking…" / green / red "Already taken" / red rule | username check | :265-380 | – |
| settings/profile-save-error | toast | PUT 500 | :248 | – |
| settings/preview-modal / -error | "Profile preview" sheet (ProfileView embedded) / toast | Preview profile | :282, 1117 | – |
| settings/cosmetics-owned / -owned-empty / -catalog / -catalog-empty / -equipped / -busy | Frames/Banners/Name colors/Titles; Owned/Catalog pills; cards Equip/Unequip; locked 60% "🔒"; outline when equipped | cosmetics tab | :852-1029 | – |
| settings/preferences / -accent-active | Layout (Sidebar/Top nav), Theme (Light only), Font size, Visibility, 5 swatches + wheel / double ring | preferences tab | :448-576 | – |
| settings/notifications | 4 switches | notifications tab | :579-609 | settings-toggle-* |
| settings/data | Export, Product analytics, Danger Zone | data tab | :612-668 | settings-analytics |
| settings/data-export-success / -error | toasts | export | :633 | – |
| settings/data-analytics-{unknown, unreadable, unset, on, on-browser-blocked, on-not-running, off, off-unsaved, saving} | 9 note/switch variants | opt-out state / DNT / PATCH 500 | :737-834 | settings-analytics-note, -toggle, -reload, -retry |
| settings/data-delete-confirm | native prompt "DELETE" → / | Delete my account | :286 | – |

## /settings/connections (`components/screens/ConnectedAccounts.tsx`)
booting (null) · checking ("CHECKING…") · not-connected (Connect) · connected-password ("CREDENTIALS SAVED · PASSWORD", Last sync, Reconnect/Disconnect) · connected-sso ("SESSION COOKIES (SSO)") · status-error (toast, falls back) · sync-modal (GradescopeSyncModal, see 03) · disconnect-confirm (native). Lines :35-271.

## /admin (`components/screens/Admin.tsx`, `components/screens/admin/**`) — tabs `admin-tab-{users,allowlist,email,roles,flags,achievements,cosmetics,analytics,audit,feedback}`
| State id | What the user sees | Trigger | File:line | testids |
|---|---|---|---|---|
| admin/no-access | "You don't have admin access." | student | Admin.tsx:51 | – |
| admin/shell | "Admin Console" + red Staff only, scrolling tabs | `rich-user-admin` | :62-103 | admin-tab-* |
| admin/users-loading / -populated / -filtered / -empty / -row-variants / -role-assign / -role-chips / -remove-dialog / -remove-result / -load-error | skeleton / table + pager / filter suffix / "0 users" / "No profile name" / "Unreadable record" / inline role select / badges × / "Remove X's access?" dialog / toasts | users tab | :142-386 | admin-users-summary, admin-user-* |
| admin/allowlist-loading / -populated / -status-chips / -invite-chips / -not-configured / -no-match / -selection / -bulk-dialog / -toasts | summary counts, search, add, filter chips, bulk approve, table / chips / warn banner / "No addresses match." / indeterminate / "Approve N people?" / toasts | allowlist tab | admin/AllowlistTab.tsx:45-410 | allowlist-* , email-not-configured-banner |
| admin/email-loading / -compose / -preview-loading / -preview-error / -unknown-vars / -no-audiences / -not-configured / -confirm-dialog / -history-empty / -history-populated / -toasts | compose (subject/body counters, variables, audiences, test/send) + preview iframe; errors; "Email N people?" type-to-confirm; history rows | email tab | admin/EmailBroadcasts.tsx:158-526 | email-* |
| admin/roles / -empty / -delete-armed / -validation | preview + create form + list / "No roles yet." / "Click again" / warn toast | roles tab | Admin.tsx:391-534, 926 | – |
| admin/flags-loading / -list / -empty / -multivariant-row / -confirm-dialog / -panel / -panel-dirty / -panel-invalid / -panel-overrides / -student-results / -explain-result / -tooltips | grouped flag rows (rollout/overrides chips, last changed, Visible/Hidden, switch) / "Make Quiz hidden?" / right Sheet: Everyone, Gradual rollout presets + slider, Overrides, Check a student; sticky Save footer | flags tab | admin/FeatureFlags.tsx:33-235; FlagPanel.tsx:25-411 | flag-* |
| admin/achievements-loading / achievements / -empty-variants / achievement-card / -card-expanded / -icon-error / xp-rules / grant-panel | live/WIP grids w/ filters, card (Edit/Publish/Unpublish), expanded editor (icon dropzone, triggers, cosmetics), XP rules, Grant | achievements tab | admin/AchievementWiki.tsx:30-837 | – |
| admin/cosmetics / -row-expanded / -validation | create form + 4 type cards / role chips / warn toasts | cosmetics tab | Admin.tsx:538-797 | – |
| admin/analytics-overview-loading / -overview / -empty / -error | 4 MetricCards, 2 sparklines, Role membership | analytics tab | :815-874 | – |
| admin/audit | "N recorded actions", filters, table, pager | audit tab | :1005-1102 | – |
| admin/feedback / -empty | Feedback + Issue reports cards | feedback tab | :1105-1180 | adminfb-* |

## /admin/analytics (`components/screens/AdminAnalytics.tsx`, `AnalyticsCharts.tsx`) — URL only, no in-app link
no-access · loading (range bar 7d/30d/90d + dates, "—", "Loading…") · populated (stat row; Usage line + top events + table; Top users sortable; LLM cost grouped feature/user/model; Errors lines + feed) · panel-error (+ Try again) · background-error (toast) · truncated (red chip) · empty-chart ("No data in this range.") · users-empty · errors-empty ("No errors in this range. 🎉") · error-rate-variants · chart-hover (crosshair tooltip) · sort-active. testids `admin-analytics-range-*`, `-cost-group-*`, `-users-sort-*`, `-{panel}-retry`. Lines :69-575.

## Pre-shell
| State id | What the user sees | Trigger | File:line | testids |
|---|---|---|---|---|
| onboarding/step-0-welcome | card, 6 dots, "Welcome to Sapling", Continue, × | `rich-user-new` / draft step 0 | Onboarding.tsx:173-288 | onboarding-gate, -close, -continue |
| onboarding/step-1-name | First/Last, Continue disabled until filled | step 1 | :314 | onboarding-first-name, -last-name, -back |
| onboarding/step-2-school | School (BU, disabled), Year | step 2 | :336 | onboarding-school |
| onboarding/step-3-academics | Majors/Minors chip inputs | step 3 | :358-421 | onboarding-chip-* |
| onboarding/step-4-courses / -searching / -empty | search, chips, results ✓ / "Searching…" / "No courses match." | step 4 | :423-523 | onboarding-course-* |
| onboarding/step-5-style | 5 radio cards, "Enter Sapling →" | step 5 | :525 | onboarding-learning-style-* |
| onboarding/submitting / -submit-success / -submit-error | "Saving…" / toast → /dashboard / toast | profile POST | :163-269 | – |
| pending/loading / unknown / not-on-waitlist / join-error / on-waitlist / just-joined | sprout card "Your account isn't approved yet" variants | `/pending?t=x` + status mocks | app/pending/page.tsx:205-257 | pending-* |
| setting-up/waiting / failed | "Setting up your sample data…" / failed + Retrying + Continue anyway | local-seed state | app/setting-up/page.tsx:91-96 | setup-gate, setup-error, setup-continue |
| auth-callback/signing-in | "Signing you in…" | /auth/callback | app/auth/callback/page.tsx:126 | – |
| auth/not-signed-in | → OAuth or `/?error=<code>` SignInModal copy (session_expired, env_misconfig, google_not_configured, signin_failed, not_approved, invalid_domain, revoked, oauth_denied, unknown) | middleware | middleware.ts:41-97; marketing/SignInModal.tsx:13 | – |
| auth/client-bounce | → `/?error=session_expired` | /api/auth/me 401 | context/UserContext.tsx:295 | – |

## App chrome & global
| State id | What the user sees | Trigger | File:line | testids |
|---|---|---|---|---|
| shell/sidebar-expanded | 200px olive rail, groups Learn/Organize/Community/Tools, Collapse, Settings/Admin/avatar footer | default ≥768 | ShellFrame.tsx:24; SideNav.tsx:107 | app-shell, nav-link-* |
| shell/sidebar-collapsed | 64px icons only | Collapse / localStorage | SideNav.tsx:113-271 | – |
| shell/nav-item-active / hover | cream wash + bold / half wash | route / hover | SideNav.tsx:87 | – |
| shell/topnav-desktop / -group-open | 56px bar, group triggers, cog/shield/avatar / dropdown | `sapling_layout=topnav` | TopNav.tsx:49-371 | – |
| shell/topnav-mobile / -mobile-open | hamburger / X + grouped 44px rows | < 768 | TopNav.tsx:98, 438 | – |
| shell/role-student vs admin | Admin item/shield only for admins | persona | SideNav.tsx:294 | – |
| shell/flags-loading / flag-hidden-{feature} | flagged items held back / removed + route redirect | `/api/flags` | lib/navFeatures.ts:13-66; NavFeatureGate.tsx | nav-feature-gate |
| shell/route-loading | content skeleton | transition | app/(shell)/loading.tsx | shell-loading |
| shell/skip-link | "Skip to content" | Tab | ShellFrame.tsx:41 | – |
| global/error-segment / -root | "Something interrupted us" + 4 headlines, Try again, Report this | render error | app/error.tsx; global-error.tsx; ErrorBoundary.tsx:41 | error-fallback |
| fab/report | bottom-right "🔔 Report" | always | FloatingActions.tsx | – |
| modal/report-issue / -toasts | type pills, textarea, ≤5 screenshots, Submit | Report | ReportIssueFlow.tsx:67-124 | – |
| modal/feedback-global | "What's clicking?" 1–5, chips, textarea | 45s / `?testFeedback=global` | FeedbackFlow.tsx:104 | – |
| modal/session-feedback-step-0..3 | "How was that session?" 4 steps | leave /learn / `?testFeedback=session` | SessionFeedbackFlow.tsx:99-243 | – |
| modal/disclaimer | "Heads up / Sapling uses AI" | first /learn or /quiz | DisclaimerModal.tsx | – |
| toast/{default,success,error,warn,info} | top-right stack, 5s | toast.* | ToastProvider.tsx:84-155 | – |
| toast/achievement-unlock | rarity icon + name | unlock (sidebar layout only) | AchievementUnlockToast.tsx; ShellFrame.tsx:89 | – |
| overlay/dialog | sm 420 / md 520 / lg 640 / xl 760 | Dialog | Dialog.tsx:386 | – |
| overlay/sheet | right slide-in | Sheet | ui/Sheet.tsx | – |
| companion/shell / lightbox | public chrome header/footer / screenshot viewer | public pages | companion/CompanionShell.tsx:63; Lightbox.tsx | – |

TopBar is the per-page header only (breadcrumb, serif title, subtitle, actions) — there is NO avatar menu or notifications UI anywhere.

## Nav transitions
`nav-link-{dashboard,learn("Tutor"),quiz,tree,study,library,calendar,social,achievements,gradebook("Grades"),notetaker,course-planner,settings,admin}` → matching route; wordmark → /dashboard. Sidebar ↔ collapsed; TopNav group open/close; mobile hamburger; Preferences layout select switches skin live; flagged route → /dashboard. Sign-in → /auth/callback → /pending | /setting-up | /onboarding | /dashboard. Onboarding continue/back; step 5 → /dashboard; × or Esc signs out. Pending join / sign out / home. Report FAB → modal. Leaving /learn → session feedback.

## UI primitives & variants (for the Figma library)
- **Button** (`ui/Button.tsx`, globals.css:233-247, 715-745): secondary, primary (forest), ghost, danger, link; sizes sm/md/lg/xl; hover, disabled.
- **Chip** (`ui/Chip.tsx`): neutral, accent, warn, err, info, optional icon.
- **Badge**: custom hue border + 12% tint (rarity/role/grade); RoleBadge.
- **Toggle** (`ui/Toggle.tsx`): pill segmented, sm/md, selected forest.
- **Switch** (`ui/Switch.tsx`): off/on/disabled/focus; Settings has its own 36×20 inline variant.
- **SegmentedControl**: mono uppercase, accent underline, disabled, hover.
- **AnswerOption**: default, selected, correct, chosen-wrong, muted, letter slot.
- **FilterPills / Pill**: active/inactive, custom color, icon, sm/md.
- **EmptyState**: md / hero; icon, eyebrow, body, action.
- **InlineBanner**: accent / neutral.
- **ProgressDots**: row/column; current/done/todo (onboarding has its own pill dots).
- **Tooltip / InfoTip**: top/bottom; round "?".
- **Sheet**, **Dialog** (sm/md/lg/xl, optional title/close, non-dismissible), **Toast** (5 tones).
- **Skeletons** (`Skeleton.tsx`): base, text, Settings, AdminTable, Library, Profile, Dashboard, Calendar, Achievements, Social, Graph, StudyGuide, Flashcards.
- **Also:** CustomSelect (sm/default, placeholder, disabled options), Avatar (28/30/44/52/72, image/initials), CatalogRow armed delete, EmailNotConfiguredBanner.

## Uncertain / needs a human
1. Settings load failure has no error UI (skeleton forever).
2. No avatar menu / notifications exist — confirm nothing planned.
3. /admin/analytics has no in-app entry — invent a link in the prototype?
4. Audit endpoint path assumed (`lib/api.ts:1389`).
5. AchievementUnlockWatcher only mounted in sidebar layout — possible bug.
6. Esc on /onboarding signs out (same as ×).
7. Native prompt/confirm/alert dialogs can't be prototyped faithfully.
8. Analytics DNT/GPC/blocked notes need browser env.
9. Theme = light only (no dark variant).
10. Mobile mostly CSS-only; Settings tab rail stays a fixed 200px column on phones — may look broken.
