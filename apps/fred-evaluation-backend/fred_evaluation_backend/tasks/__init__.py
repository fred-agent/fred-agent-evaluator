# Canonical task-event surface for the evaluator.
#
# Exposes evaluation runs through the platform-canonical task-event shape
# from fred-core (`EvaluationTaskEvent` / `EvaluationDetail`, fred-core >= 3.2.0),
# so the frontend reuses the shared Task components (TaskStateBadge /
# TaskProgressBar / TaskTray) with no per-service adapter. This module only adds
# the read-side mapping from an evaluation run row onto that shape.
