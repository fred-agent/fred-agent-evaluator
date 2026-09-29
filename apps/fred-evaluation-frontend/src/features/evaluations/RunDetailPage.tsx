import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Chip, Dialog, Spinner } from "@fred-oss/ui";
import { useAppNavigate } from "../../app/router";
import { useShellElement } from "../../app/shell";
import { useLoad } from "../../shared/api/useLoad";
import type {
  EvaluationRun,
  RunAnalysis,
  RunCase,
} from "../../shared/api/schemas";
import { LoadFailure } from "./LoadFailure";
import {
  describeError,
  formatDate,
  formatScore,
  isTerminal,
  stateLabel,
  verdictLabel,
} from "./presentation";
import { useEvaluationApi } from "./useEvaluationApi";

const POLL_MS = 3000;

interface RunView {
  run: EvaluationRun;
  cases: RunCase[];
}

function download(filename: string, content: unknown) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(content, null, 2)], { type: "application/json" }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function CasesTable({ cases }: { cases: RunCase[] }) {
  const { t } = useTranslation();
  return (
    <div className="evaluation-table-wrap">
      <table>
        <caption className="visually-hidden">{t("cases.title")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("cases.input")}</th>
            <th scope="col">{t("runs.verdict")}</th>
            <th scope="col">{t("cases.metrics")}</th>
            <th scope="col">{t("cases.model")}</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => (
            <tr key={c.case_id}>
              <td>
                <details>
                  <summary>{c.input}</summary>
                  <dl className="evaluation-case">
                    <dt>{t("cases.expected")}</dt>
                    <dd>{c.expected_output ?? "—"}</dd>
                    <dt>{t("cases.actual")}</dt>
                    <dd>{c.actual_output ?? "—"}</dd>
                    {c.execution_error && (
                      <>
                        <dt>{t("cases.error")}</dt>
                        <dd className="evaluation-error">
                          {c.execution_error}
                        </dd>
                      </>
                    )}
                    {c.metrics
                      .filter((m) => m.explanation || m.error)
                      .map((m) => (
                        <div key={m.name}>
                          <dt>{m.name}</dt>
                          <dd>{m.error ?? m.explanation}</dd>
                        </div>
                      ))}
                  </dl>
                </details>
              </td>
              <td>
                <Chip label={verdictLabel(c.verdict, t)} />
              </td>
              <td>
                <ul className="evaluation-inline-list">
                  {c.metrics.map((m) => (
                    <li key={m.name}>
                      {t(`metrics.${m.name}`, { defaultValue: m.name })}{" "}
                      {formatScore(m.score)}
                    </li>
                  ))}
                </ul>
              </td>
              <td>{c.actual_model_name ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AnalysisPanel({ analysis }: { analysis: RunAnalysis }) {
  const { t } = useTranslation();
  const result = analysis.analysis;
  const lists: Array<[string, string[]]> = [
    ["analysis.strengths", result.strengths],
    ["analysis.weaknesses", result.weaknesses],
    ["analysis.recommendations", result.recommendations],
  ];
  return (
    <section aria-labelledby="analysis-title" className="evaluation-panel">
      <h2 id="analysis-title">
        {t("analysis.title")} <Chip label={result.risk_level} />
      </h2>
      <p>{result.summary}</p>
      {lists.map(([key, items]) =>
        items.length ? (
          <div key={key}>
            <h3>{t(key)}</h3>
            <ul>
              {items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        ) : null,
      )}
    </section>
  );
}

/** One run: its progress while it runs, its results once done. */
export function RunDetailPage({ runId }: { runId: string }) {
  const { t, i18n } = useTranslation();
  const api = useEvaluationApi();
  const go = useAppNavigate();
  const shell = useShellElement();
  const [analysis, setAnalysis] = useState<RunAnalysis | null>(null);
  const [busy, setBusy] = useState<
    "cancel" | "analyze" | "report" | "delete" | null
  >(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const load = useCallback(async (): Promise<RunView> => {
    const [run, cases] = await Promise.all([
      api.getRun(runId),
      api.listRunCases(runId),
    ]);
    return { run, cases: cases.cases };
  }, [api, runId]);
  const { state, retry, reload } = useLoad(load, (view) =>
    isTerminal(view.run.operational_state) ? null : POLL_MS,
  );

  const act = async (
    kind: NonNullable<typeof busy>,
    action: () => Promise<void>,
  ) => {
    setBusy(kind);
    setActionError(null);
    try {
      await action();
    } catch (error) {
      setActionError(describeError(error, t));
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
  const title = `${run.snapshot.evaluation_name} ${run.snapshot.evaluation_version}`;

  return (
    <section aria-labelledby="run-title">
      <div>
        <Button
          color="on-surface"
          variant="text"
          size="small"
          onClick={() => go(`evaluations/${run.evaluation_id}`)}
        >
          {t("runs.backToEvaluation")}
        </Button>
      </div>
      <header className="evaluation-toolbar">
        <div>
          <h1 id="run-title">{title}</h1>
          <span>
            {formatDate(run.created_at, i18n.language)}
            {run.agent_model_override && ` · ${run.agent_model_override}`}
          </span>
        </div>
        <div className="evaluation-actions">
          <Chip label={stateLabel(run.operational_state, t)} />
          <Chip label={verdictLabel(run.verdict, t)} />
        </div>
      </header>
      <div className="evaluation-progress">
        <progress
          value={run.completed_cases}
          max={Math.max(run.total_cases, 1)}
          aria-label={t("runs.progress")}
        />
        <span>
          {t("runs.progressText", {
            completed: run.completed_cases,
            total: run.total_cases,
          })}
        </span>
      </div>
      <dl className="evaluation-kpis">
        <div>
          <dt>{t("runs.passed")}</dt>
          <dd>{run.passed_cases}</dd>
        </div>
        <div>
          <dt>{t("runs.failed")}</dt>
          <dd>{run.failed_cases}</dd>
        </div>
        <div>
          <dt>{t("runs.insufficient")}</dt>
          <dd>{run.insufficient_cases}</dd>
        </div>
        <div>
          <dt>{t("runs.errors")}</dt>
          <dd>{run.execution_error_cases + run.scoring_error_cases}</dd>
        </div>
      </dl>
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
        {terminal && (
          <Button
            color="primary"
            variant="outlined"
            size="small"
            disabled={busy !== null}
            onClick={() =>
              void act("report", async () =>
                download(
                  `evaluation-run-${runId}.json`,
                  await api.getRunReport(runId),
                ),
              )
            }
          >
            {t("runs.report")}
          </Button>
        )}
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
      {actionError && (
        <p role="alert" className="evaluation-error">
          {actionError}
        </p>
      )}
      {analysis && <AnalysisPanel analysis={analysis} />}
      <h2>{t("cases.title")}</h2>
      {cases.length === 0 ? (
        <p>{t("cases.empty")}</p>
      ) : (
        <CasesTable cases={cases} />
      )}
      <Dialog
        open={confirmDelete}
        title={t("runs.deleteTitle")}
        confirmLabel={t("delete")}
        cancelLabel={t("cancel")}
        confirmColor="error"
        onConfirm={() => {
          setConfirmDelete(false);
          void act("delete", async () => {
            await api.deleteRun(runId);
            go(`evaluations/${run.evaluation_id}`);
          });
        }}
        onCancel={() => setConfirmDelete(false)}
        portalContainer={shell}
      >
        <p>{t("runs.deletePrompt")}</p>
      </Dialog>
    </section>
  );
}
