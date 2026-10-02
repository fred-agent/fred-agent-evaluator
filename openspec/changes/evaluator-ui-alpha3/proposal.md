## Why

The hosted evaluator works but lacks the controls and presentation needed for parity with Fred's evaluation screens. Implement [issue #53](https://github.com/fred-agent/fred-agent-evaluator/issues/53) to exercise the unpublished UI alpha.3 package against a real consumer before release.

## What Changes

- Rebuild the five existing screens using the shared UI components, token-based layout, localized statuses, notices and toasts.
- Add server search/sort/pagination, confirmed deletion, rerun with original settings, run/case previews, richer results and editable custom metrics.
- Validate locally against the tarball built from Fred's current #2887 branch. Keep local dependency references out of committed manifests and lockfiles.
- Update frontend tests and the README. Final registry dependency validation and delivery wait for published alpha.3.

## Capabilities

### New Capabilities

- `evaluation-ui`: hosted evaluation browsing, creation, run management and result inspection. No existing OpenSpec capability is present in this repository.

### Modified Capabilities

None.

## Impact

`apps/fred-evaluation-frontend` only: feature screens, API query options, presentation helpers, i18n, styles, provider wiring, tests and README. Existing generated API types and host request/download bridge remain authoritative. No backend, authorization, worker, deployment or host changes. The SDK producer is consumed as a packed artifact; any discovered SDK defect is reported separately.
