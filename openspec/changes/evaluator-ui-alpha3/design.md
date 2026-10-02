## Context

See proposal.md for motivation and issue #53 for the screen inventory. The frontend currently pins UI alpha.2; the producer branch exports alpha.3 and all requested components. The evaluator has no previous OpenSpec root. Existing API wrappers fix list limits and sort; the five pages use raw controls and Chip for status. Generated schemas already expose RunSpec, run snapshots, results and analysis. useLoad discards stale responses and retains data during polling.

## Goals / Non-Goals

**Goals:** exercise the actual distributable SDK in the hosted application, preserve team/locale/theme context, and implement the issue's complete UI scope.

**Non-Goals:** change backend contracts, auth, worker execution, host registration or the SDK release process; add Langfuse links, instance tools or model profile display names; remove Fred's original screens.

## Decisions

1. Build with `make pack-ui` in this Fred checkout and install the resulting `libs/frontend/target/archives/fred-oss-ui-0.1.0-alpha.3.tgz` into the evaluator using npm's no-save/no-package-lock mode. Verify the installed version and packed exports. Use the packed module instead of source aliases or npm link so packaging defects remain visible. Keep existing manifests untouched during local validation. After publication, pin alpha.3, regenerate the registry lockfile and update EXPECTED in check-boundary.mjs. Do not weaken its registry checks or commit tarball references.
2. Keep existing routes, host navigation, generated types and ApplicationService. Extend list query options with debounced q, sort, offset and limit; reset offset on filter/sort changes. Use server totals for pagination and summary endpoint for evaluation KPIs. Polling must not depend solely on the currently visible run page; the summary can indicate live runs elsewhere.
3. Reuse shared components directly. Add one local status mapping in presentation.ts and ToastProvider within the existing shell/provider tree. Pass the shell portal container and localized labels where the SDK requires them. Keep shell.css limited to shell layout and visually-hidden; feature layout styles use tokens and no replicated shared-component appearance.
4. Rerun reconstructs RunSpec from the source run's target, metrics and custom_metrics, preserves its model override when present, tracks busy state per run and navigates to the newly created run. Historical runtime_agent targets cannot be submitted by the current hosted creation contract: disable that rerun with a localized explanation. Row action clicks must not trigger the preview drawer.
5. Drawers load details using existing hosted routes, isolate loading/errors, ignore stale responses on selection changes and provide keyboard access. Run previews link each case to the run detail with a case selection encoded in the host-managed route; selecting that route opens the full case drawer. Keep JSON export/copy actions inside the iframe and surface failures through toasts.
6. Use backend-provided aggregate metric scores and case counts where available. Label live scores partial; absent scores render as unavailable rather than zero. Preserve document.ts import/manual validation. Send only complete custom metric rows with the supported parameter names and a valid threshold; half-filled rows never reach the API.

## Risks / Trade-offs

- Unpublished alpha.3 → local build/tests can pass while registry-bound quality remains pending; report these separately and do not claim final acceptance before publication.
- Real consumer finds SDK styling or interaction defects → report a focused producer defect with reproduction; do not recreate the component locally.
- Drawers, polling and pagination race → test delayed responses, selection changes and live runs outside the current page.
- Clipboard and download behavior differs inside hosted iframes → validate in Fred, including failure feedback.

## Migration Plan

Validate locally with the packed SDK. On 2026-10-02 the developer explicitly authorized committing the implementation before publication, superseding the original commit gate in issue #53. After publication, resolve exact registry alpha.3, run root quality/tests and frontend build, then push a draft PR and reconcile/archive the specs after verification and required review. Rollback uses the previous frontend image; there is no data migration.


## Approved consumer-driven SDK extensions

The developer explicitly approved modifications in both repositories. Fred's
`complete-hosted-ui-interactions` change adds optional DataTable.onRowClick,
InlineDrawer.closeLabel and KpiStatCard.tone to canonical shared inputs. The
evaluator consumes the rebuilt alpha.3 archive; no local component replica or
registry boundary exception is introduced.

## Visual refinement pilot — run creation (2026-10-01)

The developer requested a visual comparison with Fred and one representative screen before broader rollout. Live comparison of Agents, Resources and Evaluations found that the evaluator references Geist tokens but never imports the packaged font faces. The list also overallocates width to filtering; the run form stretches controls across the page, mixes metric labels and descriptions inline, and leaves its recap/actions below a long stack.

Load the existing packaged Geist font globally. Limit the composition pilot to RunCreatePage: shared PageHeader/Breadcrumb, compact agent/model fields, stacked metric labels/help with aligned switches, collapsed custom metrics and a side recap containing the primary action. Stack columns at narrower widths; preserve RunSpec and validation. Other screens retain their layouts for now. Use CSS modules and existing tokens; do not override SDK component internals.
