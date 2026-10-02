import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Breadcrumb,
  Button,
  DataTable,
  Dialog,
  Disclosure,
  KpiStatCard,
  PageEmptyState,
  PageHeader,
  ProgressBar,
  Spinner,
  StatusBadge,
  useToast,
} from "@fred-oss/ui";
import { useAppNavigate } from "../../app/router";
import { useShellElement } from "../../app/shell";
import { useLoad } from "../../shared/api/useLoad";
import type { RunAnalysis } from "../../shared/api/schemas";
import { LoadFailure } from "./LoadFailure";
import {
  describeError,
  downloadJson,
  formatDate,
  formatScore,
  isTerminal,
  statusPresentation,
} from "./presentation";
import { useEvaluationApi } from "./useEvaluationApi";
import { useTableLabels } from "./ListControls";
import { CaseDrawer } from "./CaseDrawer";

export function RunDetailPage({
  runId,
  caseId,
}: {
  runId: string;
  caseId?: string;
}) {
  const { t, i18n } = useTranslation();
  const api = useEvaluationApi();
  const go = useAppNavigate();
  const shell = useShellElement();
  const toast = useToast();
  const labels = useTableLabels();
  const [analysis, setAnalysis] = useState<RunAnalysis | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const load = useCallback(async () => {
    const [run, cases] = await Promise.all([
      api.getRun(runId),
      api.listRunCases(runId),
    ]);
    return { run, cases: cases.cases };
  }, [api, runId]);
  const { state, retry, reload } = useLoad(load, (view) =>
    isTerminal(view.run.operational_state) ? null : 3000,
  );
  const act = async (kind: string, action: () => Promise<void>) => {
    if (busy !== null) return;
    setBusy(kind);
    try {
      await action();
      toast.showSuccess({ summary: t("ui.done") });
    } catch (error) {
      toast.showError({ summary: describeError(error, t) });
    } finally {
      setBusy(null);
    }
  };
  if (state.status === "loading")
    return <Spinner statusText={t("loadingPage")} />;
  if (state.status === "error")
    return <LoadFailure error={state.error} onRetry={retry} />;
  const { run, cases } = state.data;
  const terminal = isTerminal(run.operational_state);
  const completed = ["completed", "succeeded"].includes(run.operational_state);
  const metricScores = new Map<string, number[]>();
  for (const row of cases)
    for (const metric of row.metrics)
      if (metric.score !== null && Number.isFinite(metric.score))
        metricScores.set(metric.name, [
          ...(metricScores.get(metric.name) ?? []),
          metric.score,
        ]);
  const averages = [...metricScores].map(([name, scores]) => ({
    name,
    score: scores.reduce((sum, score) => sum + score, 0) / scores.length,
  }));
  const global = averages.length
    ? averages.reduce((sum, metric) => sum + metric.score, 0) / averages.length
    : null;
  const stats = [
    ["runs.passed", run.passed_cases, "passed"],
    ["runs.failed", run.failed_cases, "failed"],
    ["runs.insufficient", run.insufficient_cases, "insufficient"],
    ["ui.executionErrors", run.execution_error_cases, "error"],
    ["ui.scoringErrors", run.scoring_error_cases, "error"],
  ] as const;
  return (
    <section>
      <PageHeader
        title={`${run.snapshot.evaluation_name} ${run.snapshot.evaluation_version}`}
        breadcrumb={
          <Breadcrumb
            segments={[
              { label: t("evaluations.title"), onClick: () => go("") },
              {
                label: run.snapshot.evaluation_name,
                onClick: () => go(`evaluations/${run.evaluation_id}`),
              },
              { label: runId.slice(0, 8) },
            ]}
          />
        }
      />
      <div className="evaluation-actions">
        <StatusBadge
          {...statusPresentation(run.operational_state, "states", t)}
        />
        <StatusBadge {...statusPresentation(run.verdict, "verdicts", t)} />
        <span>
          {t("ui.passRate", {
            passed: run.passed_cases,
            total: run.total_cases,
            rate: run.total_cases
              ? Math.round((100 * run.passed_cases) / run.total_cases)
              : 0,
          })}
        </span>
      </div>
      <div className="evaluation-stack">
        {!terminal && (
          <ProgressBar
            theme="primary"
            current={run.completed_cases}
            max={Math.max(1, run.total_cases)}
          />
        )}
        <span>
          {t("runs.progressText", {
            completed: run.completed_cases,
            total: run.total_cases,
          })}
        </span>
      </div>
      <div className="evaluation-kpis">
        {stats.map(([key, value, verdict]) => (
          <KpiStatCard
            key={key}
            label={t(key)}
            value={value}
            tone={statusPresentation(verdict, "verdicts", t).tone}
            isLoading={false}
            isError={false}
          />
        ))}
      </div>
      <section className="evaluation-stack">
        <h2>
          {t("ui.averages")}
          {!terminal && ` · ${t("ui.partial")}`}
        </h2>
        <p>
          {t("ui.globalScore")}: {formatScore(global)}
        </p>
        {averages.map((metric) => (
          <div key={metric.name}>
            <span>
              {t(`metrics.${metric.name}`, { defaultValue: metric.name })}{" "}
              {formatScore(metric.score)}
            </span>
            <ProgressBar theme="primary" current={metric.score} max={1} />
          </div>
        ))}
      </section>
      <div className="evaluation-actions">
        {!terminal && (
          <Button
            color="error"
            variant="outlined"
            size="small"
            disabled={busy !== null}
            onClick={() =>
              void act("cancel", async () => {
                await api.cancelRun(runId);
                reload();
              })
            }
          >
            {t("runs.cancel")}
          </Button>
        )}
        {completed && (
          <Button
            color="primary"
            variant="filled"
            size="small"
            disabled={busy !== null}
            onClick={() =>
              void act("analyze", async () =>
                setAnalysis(await api.analyzeRun(runId)),
              )
            }
          >
            {busy === "analyze" ? t("analysis.running") : t("analysis.run")}
          </Button>
        )}
        <Button
          color="primary"
          variant="outlined"
          size="small"
          disabled={busy !== null}
          onClick={() =>
            void act("report", async () =>
              downloadJson(
                `evaluation-run-${runId}.json`,
                await api.getRunReport(runId),
              ),
            )
          }
        >
          {t("runs.report")}
        </Button>
        {terminal && (
          <Button
            color="error"
            variant="text"
            size="small"
            disabled={busy !== null}
            onClick={() => setConfirmDelete(true)}
          >
            {t("delete")}
          </Button>
        )}
      </div>
      {analysis && (
        <section className="evaluation-stack">
          <div className="evaluation-actions">
            <h2>{t("analysis.title")}</h2>
            <StatusBadge
              {...statusPresentation(analysis.analysis.risk_level, "risk", t)}
            />
            <Button
              color="on-surface"
              variant="text"
              size="small"
              onClick={() => setAnalysis(null)}
            >
              {t("ui.dismiss")}
            </Button>
          </div>
          <p>{analysis.analysis.summary}</p>
          {(["strengths", "weaknesses", "recommendations"] as const).map(
            (key) => (
              <div key={key}>
                <h3>{t(`analysis.${key}`)}</h3>
                <ul>
                  {analysis.analysis[key].map((item, index) => (
                    <li key={index}>{item}</li>
                  ))}
                </ul>
              </div>
            ),
          )}
        </section>
      )}
      <Disclosure title={t("ui.metadata")}>
        <dl className="evaluation-metadata">
          {[
            [t("evaluations.name"), run.snapshot.evaluation_name],
            [t("evaluations.version"), run.snapshot.evaluation_version],
            [t("evaluations.author"), run.created_by],
            [t("ui.judge"), run.judge_profile_id],
            [
              t("runCreate.model"),
              run.agent_model_override ?? t("runCreate.teamDefault"),
            ],
            [
              t("evaluations.created"),
              formatDate(run.created_at, i18n.language),
            ],
            [t("runs.started"), formatDate(run.started_at, i18n.language)],
            [t("ui.completedAt"), formatDate(run.completed_at, i18n.language)],
          ].map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </Disclosure>
      <h2>{t("cases.title")}</h2>
      {cases.length === 0 ? (
        <PageEmptyState icon="article" message={t("cases.empty")} />
      ) : (
        <div
          className="evaluation-table-wrap"
          role="region"
          aria-label={t("cases.title")}
        >
          <DataTable
            data={cases}
            onRowClick={(row) =>
              go(`runs/${runId}/cases/${encodeURIComponent(row.case_id)}`)
            }
            labels={labels}
            rowKey={(row) => row.case_id}
            pageSize={20}
            columns={[
              {
                label: t("ui.id"),
                cellRenderer: (row) => (
                  <Button
                    color="primary"
                    variant="text"
                    size="small"
                    onClick={() =>
                      go(
                        `runs/${runId}/cases/${encodeURIComponent(row.case_id)}`,
                      )
                    }
                  >
                    {row.case_id}
                  </Button>
                ),
              },
              {
                label: t("cases.input"),
                size: "minmax(12rem, 2fr)",
                cellRenderer: (row) => row.input,
              },
              {
                label: t("runs.state"),
                cellRenderer: (row) => (
                  <StatusBadge
                    {...statusPresentation(row.status, "states", t)}
                  />
                ),
              },
              {
                label: t("runs.verdict"),
                cellRenderer: (row) => (
                  <StatusBadge
                    {...statusPresentation(row.verdict, "verdicts", t)}
                  />
                ),
              },
              {
                label: t("ui.latency"),
                cellRenderer: (row) =>
                  row.latency_ms === null ? "—" : `${row.latency_ms} ms`,
              },
              {
                label: t("cases.metrics"),
                size: "14rem",
                cellRenderer: (row) => (
                  <div>
                    {row.metrics.slice(0, 2).map((metric) => (
                      <div key={metric.name}>
                        {t(`metrics.${metric.name}`, {
                          defaultValue: metric.name,
                        })}{" "}
                        {formatScore(metric.score)}
                      </div>
                    ))}
                  </div>
                ),
              },
            ]}
          />
        </div>
      )}
      {caseId && (
        <CaseDrawer
          key={caseId}
          runId={runId}
          caseId={caseId}
          onClose={() => go(`runs/${runId}`)}
        />
      )}
      <Dialog
        open={confirmDelete}
        title={t("runs.deleteTitle")}
        confirmLabel={t("delete")}
        cancelLabel={t("cancel")}
        confirmColor="error"
        onConfirm={() =>
          void act("delete", async () => {
            await api.deleteRun(runId);
            setConfirmDelete(false);
            go(`evaluations/${run.evaluation_id}`);
          })
        }
        onCancel={() => setConfirmDelete(false)}
        portalContainer={shell}
      >
        <p>{t("runs.deletePrompt")}</p>
      </Dialog>
    </section>
  );
}
