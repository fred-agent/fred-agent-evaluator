## Purpose

Let team members create evaluations, manage runs and inspect their results through the hosted Fred evaluation application.

## ADDED Requirements

### Requirement: Browse and manage evaluations
The UI SHALL provide a titled list with a creation action, debounced server search, created-date ascending/descending and name ascending sort, server pagination, open and confirmed delete actions, and an actionable empty state.

#### Scenario: Search and page a list
- **WHEN** the user changes search or sort and then chooses another page
- **THEN** requests carry q, sort, offset and limit, filter changes reset the offset, and pagination uses the server total

#### Scenario: Confirm deletion
- **WHEN** the user cancels or confirms a list deletion
- **THEN** cancellation leaves the evaluation intact and confirmation deletes it, refreshes the list and reports the outcome

### Requirement: Inspect and rerun an evaluation
The evaluation screen SHALL show breadcrumbs, total/running/completed/cases-evaluated/critical-failure statistics, a sorted paginated runs list with started time, target name and short id, state, live indicator, verdict and progress, and collapsible evaluation cases. Runs SHALL offer detail, rerun and confirmed delete actions; running runs cannot be deleted.

#### Scenario: Rerun a supported target
- **WHEN** the user reruns a managed-instance run
- **THEN** a new run uses the original target, built-in metrics, custom metrics and optional model override, only that row is busy, and success opens the new run

#### Scenario: Historical target cannot be recreated
- **WHEN** a historical run targets a runtime agent
- **THEN** rerun is unavailable with an explanation because the current creation API accepts managed instances only

#### Scenario: Preview a run
- **WHEN** the user activates a run row
- **THEN** a drawer previews case verdicts and metric scores, and each case links to its full detail

### Requirement: Inspect run outcomes and case details
The run screen SHALL show breadcrumbs, state/verdict/pass-rate summary, live progress, separate passed/failed/insufficient/execution-error/scoring-error statistics, metric averages and global score labelled partial while live, dismissible risk analysis with strengths/weaknesses/recommendations, and collapsible metadata including evaluation/version/author/judge/model override and timestamps. It SHALL allow live cancellation, completed-run analysis, JSON report download and terminal deletion.

#### Scenario: Live run reaches terminal state
- **WHEN** polling observes a live run complete
- **THEN** counts and scores update, partial labelling ends, polling stops and actions reflect the terminal state

#### Scenario: Open a complete case
- **WHEN** the user activates a case from the table or a run-preview link
- **THEN** a drawer shows verdict, latency, status, actual model, input, expected and actual output side by side when space permits, execution/scoring errors, metric score bars/explanations and structural checks, with copy/download JSON actions

#### Scenario: Read the cases table
- **WHEN** run cases are available
- **THEN** the table shows case id, truncated input, status, verdict, latency and first metric scores

### Requirement: Create evaluations with existing document rules
The creation screen SHALL offer import/manual selection, JSON dropzone with import errors and count, manual multiline input/expected-output rows with add/remove controls, and success feedback. Existing name/version/author and at-most-200-case document rules SHALL remain unchanged.

#### Scenario: Import invalid or valid JSON
- **WHEN** the user selects or drops a document
- **THEN** invalid content shows a localized validation error and valid content populates the evaluation and displays its imported count

### Requirement: Configure a new run
The run form SHALL provide agent selection, described built-in metric switches, unavailable expected-output metrics with reasons for incomplete evaluations, editable custom metrics (name, criteria, supported parameters and threshold), optional model override and a recap of evaluation, agent and metric/model selections.

#### Scenario: Submit custom metrics
- **WHEN** the user submits complete and half-filled custom metric rows
- **THEN** only complete valid rows are included in custom_metrics, using INPUT, ACTUAL_OUTPUT, EXPECTED_OUTPUT or RETRIEVAL_CONTEXT parameters

### Requirement: Consistent accessible hosted presentation
The five screens SHALL support English/French, light/dark themes and narrow widths without horizontal page scrolling. Status, verdict and completeness SHALL use one consistent non-interactive badge mapping. Load failures and empty lists SHALL have structured notice/empty-state presentation; action outcomes SHALL use toasts. Navigation and requests SHALL continue to use host context and the team-scoped bridge.

#### Scenario: Narrow hosted screen
- **WHEN** a user opens any screen at a narrow viewport in either locale/theme
- **THEN** controls remain usable, tables scroll within their container, drawers can be opened and closed by keyboard, and no horizontal page scroll is needed

#### Scenario: Recover from a failed load or action
- **WHEN** a hosted request fails
- **THEN** a load failure offers retry and an action failure produces localized outcome feedback without losing existing results
