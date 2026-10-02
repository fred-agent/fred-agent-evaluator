import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  InlineDrawer,
  ProgressBar,
  ServiceNotice,
  Spinner,
  StatusBadge,
  useToast,
} from "@fred-oss/ui";
import { useLoad } from "../../shared/api/useLoad";
import { useEvaluationApi } from "./useEvaluationApi";
import { LoadFailure } from "./LoadFailure";
import {
  describeError,
  downloadJson,
  formatScore,
  statusPresentation,
} from "./presentation";

export function CaseDrawer({
  runId,
  caseId,
  onClose,
}: {
  runId: string;
  caseId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const api = useEvaluationApi();
  const toast = useToast();
  const load = useCallback(
    () => api.getRunCase(runId, caseId),
    [api, runId, caseId],
  );
  const { state, retry } = useLoad(load, (data) =>
    ["pending", "running", "scoring"].includes(data.status) ? 3000 : null,
  );
  const act = async (copy: boolean) => {
    if (state.status !== "ready") return;
    try {
      if (copy)
        await navigator.clipboard.writeText(
          JSON.stringify(state.data, null, 2),
        );
      else downloadJson(`evaluation-case-${caseId}.json`, state.data);
      toast.showSuccess({ summary: t(copy ? "ui.copied" : "ui.downloaded") });
    } catch (error) {
      toast.showError({ summary: describeError(error, t) });
    }
  };
  return (
    <InlineDrawer
      closeLabel={t("ui.close")}
      open
      title={`${t("cases.title")} · ${caseId}`}
      onClose={onClose}
      width="min(56rem, 100vw)"
      headerActions={
        state.status === "ready" ? (
          <div className="evaluation-actions">
            <Button
              color="primary"
              variant="text"
              size="small"
              onClick={() => void act(true)}
            >
              {t("ui.copyJson")}
            </Button>
            <Button
              color="primary"
              variant="text"
              size="small"
              onClick={() => void act(false)}
            >
              {t("ui.downloadJson")}
            </Button>
          </div>
        ) : undefined
      }
    >
      {state.status === "loading" && <Spinner statusText={t("loadingPage")} />}
      {state.status === "error" && (
        <LoadFailure error={state.error} onRetry={retry} />
      )}
      {state.status === "ready" && (
        <div className="evaluation-stack">
          <div className="evaluation-actions">
            <StatusBadge
              {...statusPresentation(state.data.verdict, "verdicts", t)}
            />
            <StatusBadge
              {...statusPresentation(state.data.status, "states", t)}
            />
            <span>
              {t("ui.latency")}:{" "}
              {state.data.latency_ms === null
                ? "—"
                : `${state.data.latency_ms} ms`}
            </span>
            <span>
              {t("cases.model")}: {state.data.actual_model_name ?? "—"}
            </span>
          </div>
          <section>
            <h3>{t("cases.input")}</h3>
            <p className="evaluation-text">{state.data.input}</p>
          </section>
          <div className="evaluation-columns">
            <section>
              <h3>{t("cases.expected")}</h3>
              <p className="evaluation-text">
                {state.data.expected_output ?? "—"}
              </p>
            </section>
            <section>
              <h3>{t("cases.actual")}</h3>
              <p className="evaluation-text">
                {state.data.actual_output ?? "—"}
              </p>
            </section>
          </div>
          {state.data.execution_error && (
            <ServiceNotice
              title={t("ui.executionErrors")}
              description={state.data.execution_error}
            />
          )}
          {state.data.scoring_errors.length > 0 && (
            <ServiceNotice
              title={t("ui.scoringErrors")}
              description={state.data.scoring_errors.join("\n")}
            />
          )}
          <h3>{t("cases.metrics")}</h3>
          {state.data.metrics.map((metric) => (
            <section key={metric.name} className="evaluation-stack">
              <div className="evaluation-actions">
                <span>
                  {t(`metrics.${metric.name}`, { defaultValue: metric.name })}{" "}
                  {formatScore(metric.score)}
                </span>
                <StatusBadge
                  {...statusPresentation(metric.verdict, "verdicts", t)}
                />
              </div>
              {metric.score !== null && (
                <ProgressBar
                  theme={metric.verdict === "failed" ? "error" : "primary"}
                  current={metric.score}
                  max={1}
                />
              )}
              {metric.explanation && (
                <p className="evaluation-text">{metric.explanation}</p>
              )}
              {metric.error && (
                <ServiceNotice
                  title={t("ui.scoringErrors")}
                  description={metric.error}
                />
              )}
            </section>
          ))}
          <h3>{t("ui.structural")}</h3>
          {state.data.structural_checks.map((check) => (
            <div key={check.name} className="evaluation-actions">
              <span>{check.name}</span>
              <StatusBadge
                {...statusPresentation(
                  check.passed === null
                    ? "pending"
                    : check.passed
                      ? "passed"
                      : "failed",
                  "verdicts",
                  t,
                )}
              />
            </div>
          ))}
        </div>
      )}
    </InlineDrawer>
  );
}
