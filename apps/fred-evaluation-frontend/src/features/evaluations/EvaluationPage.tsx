import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Breadcrumb,
  Button,
  DataTable,
  Dialog,
  Disclosure,
  IndicatorDot,
  KpiStatCard,
  PageEmptyState,
  PageHeader,
  ProgressBar,
  Spinner,
  StatusBadge,
  useToast,
  type SortState,
} from "@fred-oss/ui";
import { useAppNavigate } from "../../app/router";
import { useShellElement } from "../../app/shell";
import { useLoad } from "../../shared/api/useLoad";
import type { EvaluationRun } from "../../shared/api/schemas";
import { LoadFailure } from "./LoadFailure";
import { describeError, formatDate, statusPresentation } from "./presentation";
import { useEvaluationApi } from "./useEvaluationApi";
import { useTableLabels } from "./ListControls";
import { RunPreview } from "./RunPreview";

export function EvaluationPage({ evaluationId }: { evaluationId: string }) {
  const { t, i18n } = useTranslation();
  const api = useEvaluationApi();
  const go = useAppNavigate();
  const shell = useShellElement();
  const toast = useToast();
  const labels = useTableLabels();
  const [confirm, setConfirm] = useState<"evaluation" | EvaluationRun | null>(
    null,
  );
  const [busyRows, setBusyRows] = useState<Set<string>>(() => new Set());
  const [deleting, setDeleting] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(20);
  const [sort, setSort] = useState("created_at:desc");
  const load = useCallback(async () => {
    const [evaluation, summary, runs, agents] = await Promise.all([
      api.getEvaluation(evaluationId),
      api.getRunsSummary(evaluationId),
      api.listRuns(evaluationId, { offset, limit, sort }),
      api.listAgentInstances().catch(() => []),
    ]);
    return {
      evaluation,
      summary,
      runs,
      agentNames: new Map(
        agents.map((a) => [a.agent_instance_id, a.display_name]),
      ),
    };
  }, [api, evaluationId, offset, limit, sort]);
  const { state, retry, reload } = useLoad(load, (view) =>
    view.summary.running_count > 0 ? 5000 : null,
  );
  const rerun = async (run: EvaluationRun) => {
    if (run.target.kind !== "managed_instance" || busyRows.has(run.run_id))
      return;
    setBusyRows((current) => new Set(current).add(run.run_id));
    try {
      const created = await api.startRun(evaluationId, {
        target: run.target,
        metrics: run.metrics,
        custom_metrics: run.custom_metrics,
        agent_model_override: run.agent_model_override,
      });
      toast.showSuccess({ summary: t("ui.started") });
      go(`runs/${created.run_id}`);
    } catch (error) {
      toast.showError({ summary: describeError(error, t) });
    } finally {
      setBusyRows((current) => {
        const next = new Set(current);
        next.delete(run.run_id);
        return next;
      });
    }
  };
  const remove = async () => {
    if (!confirm || deleting) return;
    setDeleting(true);
    try {
      if (confirm === "evaluation") {
        await api.deleteEvaluation(evaluationId);
        go("");
      } else {
        await api.deleteRun(confirm.run_id);
        if (
          state.status === "ready" &&
          state.data.runs.runs.length === 1 &&
          offset > 0
        )
          setOffset(Math.max(0, offset - limit));
        else reload();
      }
      setConfirm(null);
      toast.showSuccess({ summary: t("ui.deleted") });
    } catch (error) {
      toast.showError({ summary: describeError(error, t) });
    } finally {
      setDeleting(false);
    }
  };
  if (state.status === "loading")
    return <Spinner statusText={t("loadingPage")} />;
  if (state.status === "error")
    return <LoadFailure error={state.error} onRetry={retry} />;
  const { evaluation, summary, runs, agentNames } = state.data;
  const fields: Record<string, string> = {
    [t("runs.started")]: "created_at",
    [t("runs.state")]: "operational_state",
    [t("runs.verdict")]: "verdict",
  };
  const [field, direction] = sort.split(":");
  const sortState: SortState = {
    columnLabel:
      Object.keys(fields).find((key) => fields[key] === field) ??
      t("runs.started"),
    direction: direction === "asc" ? "asc" : "desc",
  };
  return (
    <section>
      <PageHeader
        title={`${evaluation.name} ${evaluation.version}`}
        subtitle={`${t("evaluations.caseCount", { count: evaluation.case_count })} · ${evaluation.author ?? evaluation.created_by} · ${formatDate(evaluation.created_at, i18n.language)}`}
        breadcrumb={
          <Breadcrumb
            segments={[
              { label: t("evaluations.title"), onClick: () => go("") },
              { label: evaluation.name },
            ]}
          />
        }
        actions={
          <div className="evaluation-actions">
            <StatusBadge
              {...statusPresentation(evaluation.completeness, "evaluations", t)}
            />
            <Button
              color="error"
              variant="outlined"
              size="small"
              disabled={deleting}
              onClick={() => setConfirm("evaluation")}
            >
              {t("delete")}
            </Button>
            <Button
              color="primary"
              variant="filled"
              size="small"
              onClick={() => go(`evaluations/${evaluationId}/runs/new`)}
            >
              {t("runs.start")}
            </Button>
          </div>
        }
      />
      <div className="evaluation-kpis">
        {(
          [
            ["total", summary.total_runs],
            ["running", summary.running_count],
            ["completed", summary.completed_count],
            ["cases", summary.total_cases_completed],
            ["critical", summary.critical_error_cases],
          ] as const
        ).map(([key, value]) => (
          <KpiStatCard
            key={key}
            label={t(`runs.kpi.${key}`)}
            value={value}
            isLoading={false}
            isError={false}
          />
        ))}
      </div>
      <h2>{t("runs.title")}</h2>
      {runs.runs.length === 0 ? (
        <PageEmptyState
          icon="article"
          message={t("runs.empty")}
          action={{
            label: t("runs.start"),
            onClick: () => go(`evaluations/${evaluationId}/runs/new`),
          }}
        />
      ) : (
        <div
          className="evaluation-table-wrap"
          role="region"
          aria-label={t("runs.title")}
        >
          <DataTable
            labels={labels}
            data={runs.runs}
            onRowClick={(row) => setPreview(row.run_id)}
            rowKey={(row) => row.run_id}
            sortState={sortState}
            sortClearable={false}
            onSortChange={(next) => {
              if (next) {
                setSort(`${fields[next.columnLabel]}:${next.direction}`);
                setOffset(0);
              }
            }}
            serverPagination={{
              totalCount: runs.total,
              offset,
              limit,
              onOffsetChange: setOffset,
              onLimitChange: (value) => {
                setLimit(value);
                setOffset(0);
              },
            }}
            columns={[
              {
                label: t("runs.started"),
                size: "12rem",
                sortable: true,
                cellRenderer: (row) => (
                  <Button
                    color="primary"
                    variant="text"
                    size="small"
                    onClick={() => setPreview(row.run_id)}
                  >
                    {formatDate(
                      row.started_at ?? row.created_at,
                      i18n.language,
                    )}
                  </Button>
                ),
              },
              {
                label: t("runs.target"),
                size: "minmax(10rem, 1fr)",
                cellRenderer: (row) => {
                  const id =
                    row.target.kind === "managed_instance"
                      ? row.target.agent_instance_id
                      : row.target.agent_id;
                  return (
                    <div>
                      {agentNames.get(id) ?? id}
                      <div className="evaluation-muted">{id.slice(0, 8)}</div>
                    </div>
                  );
                },
              },
              {
                label: t("runs.state"),
                size: "10rem",
                sortable: true,
                cellRenderer: (row) => (
                  <div className="evaluation-actions">
                    {row.operational_state === "running" && (
                      <IndicatorDot
                        status="active"
                        label={t("states.running")}
                      />
                    )}
                    <StatusBadge
                      {...statusPresentation(
                        row.operational_state,
                        "states",
                        t,
                      )}
                    />
                  </div>
                ),
              },
              {
                label: t("runs.verdict"),
                size: "10rem",
                sortable: true,
                cellRenderer: (row) => (
                  <StatusBadge
                    {...statusPresentation(row.verdict, "verdicts", t)}
                  />
                ),
              },
              {
                label: t("runs.progress"),
                size: "10rem",
                cellRenderer: (row) => (
                  <div className="evaluation-progress-cell">
                    <ProgressBar
                      theme="primary"
                      current={row.completed_cases}
                      max={Math.max(1, row.total_cases)}
                    />
                    <span>
                      {row.completed_cases} / {row.total_cases}
                    </span>
                  </div>
                ),
              },
              {
                label: t("ui.actions"),
                size: "20rem",
                cellRenderer: (row) => (
                  <div className="evaluation-actions">
                    <Button
                      color="primary"
                      variant="text"
                      size="small"
                      onClick={() => go(`runs/${row.run_id}`)}
                    >
                      {t("ui.detail")}
                    </Button>
                    <Button
                      color="primary"
                      variant="text"
                      size="small"
                      title={
                        row.target.kind === "runtime_agent"
                          ? t("ui.historicalTarget")
                          : undefined
                      }
                      disabled={
                        busyRows.has(row.run_id) ||
                        row.target.kind !== "managed_instance"
                      }
                      onClick={() => void rerun(row)}
                    >
                      {t("ui.rerun")}
                    </Button>
                    <Button
                      color="error"
                      variant="text"
                      size="small"
                      disabled={
                        row.operational_state === "running" ||
                        busyRows.has(row.run_id) ||
                        deleting
                      }
                      onClick={() => setConfirm(row)}
                    >
                      {t("delete")}
                    </Button>
                  </div>
                ),
              },
            ]}
          />
        </div>
      )}
      <Disclosure
        title={t("evaluations.caseCount", { count: evaluation.case_count })}
      >
        <div className="evaluation-table-wrap">
          <DataTable
            data={evaluation.cases}
            labels={labels}
            columns={[
              { label: t("cases.input"), cellRenderer: (row) => row.input },
              {
                label: t("cases.expected"),
                cellRenderer: (row) => row.expected_output ?? "—",
              },
            ]}
          />
        </div>
      </Disclosure>
      {preview && (
        <RunPreview
          key={preview}
          runId={preview}
          onClose={() => setPreview(null)}
        />
      )}
      <Dialog
        open={confirm !== null}
        title={t(
          confirm === "evaluation"
            ? "evaluations.deleteTitle"
            : "runs.deleteTitle",
        )}
        confirmLabel={t("delete")}
        cancelLabel={t("cancel")}
        confirmColor="error"
        onConfirm={() => void remove()}
        onCancel={() => {
          if (!deleting) setConfirm(null);
        }}
        portalContainer={shell}
      >
        <p>
          {confirm === "evaluation"
            ? t("evaluations.deletePrompt", { name: evaluation.name })
            : t("runs.deletePrompt")}
        </p>
      </Dialog>
    </section>
  );
}
