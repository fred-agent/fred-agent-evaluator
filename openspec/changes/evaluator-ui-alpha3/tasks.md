## 1. Local SDK and shared presentation

- [x] 1.1 After scope confirmation, build this Fred branch with make pack-ui and install its tarball without saving dependencies or lockfile changes; verify installed alpha.3 exports, type resolution and unchanged manifests.
- [x] 1.2 Add a common localized status mapping, structured load failures/empty states and shell-scoped ToastProvider; verify status semantics, retry and action feedback in component tests.
- [x] 1.3 Extend typed API list query options and case-detail loading using existing generated schemas; verify request parameters and stale-response handling in tests.

## 2. Lists and evaluation dashboard

- [x] 2.1 Rebuild the evaluation list with PageHeader, DataTable, debounced search, supported sorts, TablePagination and open/confirmed-delete actions; test query changes, offset reset, empty results and deletion cancellation/failure/success.
- [x] 2.2 Rebuild the evaluation dashboard with Breadcrumb, five KPI cards, paginated/sorted runs, target name/id, status/verdict/progress and Disclosure cases; test totals independent of visible page and polling when live runs are outside it.
- [x] 2.3 Add per-row rerun and confirmed deletion, disabling unsupported historical-target rerun and running-run deletion; test faithful RunSpec recreation, independent busy states, navigation and errors.
- [x] 2.4 Add a run preview InlineDrawer and links that open full case detail; test row/action event isolation, keyboard activation, navigation and delayed-response selection changes.

## 3. Run results

- [x] 3.1 Rebuild run hero, progress, five outcome cards, partial/final metric scores, dismissible analysis and metadata Disclosure; test live-to-terminal updates, unavailable scores and action availability.
- [x] 3.2 Replace cases table and detail controls with DataTable and InlineDrawer displaying the complete case, errors, metrics and structural checks; test selection, close, keyboard access and route-linked case opening.
- [x] 3.3 Add case JSON copy/download feedback and preserve cancel/analyze/report/delete behavior; test failure paths and inspect exported JSON in the hosted iframe.

## 4. Creation forms

- [x] 4.1 Replace evaluation import/manual controls with SelectableCard, FileDropzone and TextArea; update tests for imports, errors, count, add/remove rows and unchanged document validation.
- [x] 4.2 Rebuild run creation with agent Select, described Switch rows and expected-output restrictions, custom metric rows, model override and recap; test supported parameters, threshold validation, half-filled omission and submitted RunSpec.

## 5. Integration and release-dependent close-out

- [x] 5.1 Complete English/French labels and token-based feature layouts, restrict shell.css to shell layout/visually-hidden, update README Screens/limits; inspect source for forbidden raw controls and component styling duplication.
- [x] 5.2 Run frontend typecheck, lint, formatting, tests and build against installed tarball; record actual commands/results here and explicitly identify the registry-bound check as pending publication.
- [ ] 5.3 Validate all five screens inside Fred in English/French, light/dark and narrow widths, including portals, keyboard, clipboard/download and live polling; record findings here and report any SDK defect separately.
- [ ] 5.4 After alpha.3 publication, pin the exact registry version, regenerate the lockfile and update boundary EXPECTED; verify no local references and run repository-root make code-quality, make test and frontend build.
- [x] 5.5 Commit the locally validated UI implementation on the existing issue branch, as explicitly authorized by the developer on 2026-10-02 before SDK publication.
- [ ] 5.6 After publication and final verification, push/open a draft PR linked to #53, complete required review, reconcile specs and archive the completed change; verify PR scope and archived capability requirements match the final implementation.


## Verification and remaining work

- Local artifact: built with `make -C /home/dimi/Fred/features/2887-ui-extension/libs/frontend pack-ui`; installed using `npx --yes npm@11 install --no-save --package-lock=false --no-audit --no-fund <archive>`. Installed UI is alpha.3; evaluator manifest/lockfile remain unchanged. npm 10 hit its documented `edgesOut` resolver failure; npm 11 succeeded.
- Repository-root `make code-quality`: passed, including backend checks and frontend API freshness, toolchain, boundary, TypeScript, Prettier and ESLint. Boundary success concerns the committed alpha.2 registry coordinates, not release acceptance of unpublished alpha.3.
- Repository-root `make test`: 36 CLI tests passed, 1 skipped; 136 backend tests passed; 38 frontend tests passed (8 new workflow tests). Python lockfile updates produced by automatic uv sync were reverted as unrelated to this UI change.
- Frontend `npm run build`: passed against installed alpha.3. No raw table/progress/details/textarea/file input remains in feature source; shell.css is limited to shell layout and visually-hidden.
- Chromium: 48 page/locale/theme/width combinations (6 routes × English/French × light/dark × 1280/390 px), no page overflow and no uncaught JavaScript error. Screenshots and diagnostic results are in `/tmp/eval-visual/`; the harness is `/tmp/eval-browser.mjs`. This uses the real distributable packages and postMessage iframe bridge with a simulated host/API, not a live Fred deployment. Full live-host validation remains pending.
- Iframe action checks (`/tmp/eval-browser-actions.mjs`): clipboard-write success feedback, downloaded JSON content and Escape closure passed. Clipboard content is covered by the frontend interaction test; Chromium clipboard-read permission was unavailable.
- Independent read-only review: stale running-run preview fixed by polling run/cases to terminal; custom metric omission retained per #53 and made explicit in the recap.
- SDK extensions approved and implemented in Fred: row activation with embedded-action isolation, localized drawer close actions and outcome KPI tones. All three APIs are consumed from the rebuilt tarball. Canonical component tests: 36 passed; producer tests: 379 passed; isolated packed-consumer typechecks/builds passed. Fred-root make code-quality passed. Evaluator frontend now has 39 passing tests, including keyboard row activation/action isolation. Publication and live deployment validation remain pending.

- The developer authorized local implementation commits on 2026-10-02, superseding issue #53's original publication gate for commits. Registry alpha.3 pin/lock/boundary updates, remaining real-host validation, PR and archive remain pending; do not mark the issue complete.


SDK close-out: Fred commit `75c5c2fee` was pushed to existing PR https://github.com/ThalesGroup/fred/pull/2890. Its additive SDK change was synced/archived after successful independent review and validation. Final evaluator make code-quality and npm run build pass with the new props. Vite is running on port 5181 with forced dependency reoptimization; restarting without --force after a same-version tarball replacement can retain old SDK code. Registry-based release acceptance remains pending alpha.3 publication.

## Visual pilot verification (2026-10-01)

- Compared live Fred Agents/Resources with evaluator list and run creation at the same 1440×1000 browser viewport. Both title styles declare Geist/22px, but evaluator omitted `@fred-oss/design-tokens/fonts.css`; its old bundle had no Geist font assets. The pilot imports the existing packaged faces (normal and italic) without a new dependency.
- Limited composition changes to RunCreatePage: compact agent/model pair, metric label/help hierarchy, collapsed custom section, responsive recap/action column and shared breadcrumb. Global font loading benefits every screen; list/results layout refinement remains pending developer feedback.
- Frontend `npm test`: 41 passed; `npm run build` passed and emits Geist assets. Root `make code-quality` passed. Custom-metric workflow test now explicitly expands the initially collapsed disclosure; submitted payload behavior remains covered.
- UI image `ghcr.io/fred-agent/fred-evaluation-ui:k3d-913a8040d706` deployed via Helm reuse-values after lint/render and import to both k3d nodes. API/worker images retained.
- Verified live French/dark pilot at 1440×1000 and 1024×900, selecting React and checking responsive layout without starting a run. Captures: `/tmp/evaluator-design-pilot/before.png`, `after.png`, `narrow.png`. Full locale/theme matrix and wider UI refinement are not completed by this pilot.
- SDK publication and the remaining visual acceptance checks are still pending under #53.

- 2026-10-02: Run table Status and Verdict columns now reserve 10rem each, preventing shared badge clipping and truncated headers. Existing DataTable horizontal scrolling handles narrower space. Typecheck, EvaluationPage's 4 tests and production build passed; rebuilt UI deployed to k3d and visually checked in live Fred at 1440px. No backend or package changes.

## Commit verification (2026-10-02)

- Developer explicitly requested committing all evaluator work on the existing `53-evaluation-ui-alpha3` branch, overriding the original pre-publication commit restriction.
- Repository-root `make code-quality`, frontend `npm test` (41 tests), and frontend `npm run build` passed. Validation uses the locally installed packed UI alpha.3.
- `npm view @fred-oss/ui@0.1.0-alpha.3 version` still returns E404. The committed dependency coordinates remain unchanged; a clean registry install cannot build these new UI screens until the published SDK is pinned. No tarball, local path or linked dependency is committed.
- The Python lockfile change caused by the quality check's automatic dependency sync was discarded; this commit contains frontend implementation, tests and associated documentation/specification only.
