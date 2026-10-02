import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  DataTable,
  Dialog,
  PageEmptyState,
  PageHeader,
  Select,
  Spinner,
  StatusBadge,
  TextInput,
  useToast,
} from "@fred-oss/ui";
import { useAppNavigate } from "../../app/router";
import { useShellElement } from "../../app/shell";
import { useLoad } from "../../shared/api/useLoad";
import type { EvaluationSummary } from "../../shared/api/schemas";
import { describeError, formatDate, statusPresentation } from "./presentation";
import { useEvaluationApi } from "./useEvaluationApi";
import { LoadFailure } from "./LoadFailure";
import { useTableLabels } from "./ListControls";

export function EvaluationsPage() {
  const { t, i18n } = useTranslation();
  const api = useEvaluationApi();
  const go = useAppNavigate();
  const shell = useShellElement();
  const toast = useToast();
  const labels = useTableLabels();
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("created_at:desc");
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(20);
  const [selected, setSelected] = useState<EvaluationSummary | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => {
      setQ(search.trim());
      setOffset(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);
  const load = useCallback(
    () => api.listEvaluations({ q, sort, offset, limit }),
    [api, q, sort, offset, limit],
  );
  const { state, retry, reload } = useLoad(load);
  const remove = async () => {
    if (!selected || busy) return;
    setBusy(true);
    try {
      await api.deleteEvaluation(selected.evaluation_id);
      setSelected(null);
      toast.showSuccess({ summary: t("ui.deleted") });
      if (
        state.status === "ready" &&
        state.data.evaluations.length === 1 &&
        offset > 0
      )
        setOffset(Math.max(0, offset - limit));
      else reload();
    } catch (error) {
      toast.showError({ summary: describeError(error, t) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <section>
      <PageHeader
        title={t("evaluations.title")}
        subtitle={
          state.status === "ready"
            ? t("evaluations.count", { count: state.data.total })
            : undefined
        }
        actions={
          <Button
            color="primary"
            variant="filled"
            size="small"
            onClick={() => go("evaluations/new")}
          >
            {t("evaluations.new")}
          </Button>
        }
      />
      <div className="evaluation-filters">
        <TextInput
          label={t("ui.search")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <Select
          size="medium"
          label={t("ui.sort")}
          value={sort}
          onChange={(value) => {
            setSort(value);
            setOffset(0);
          }}
          options={[
            {
              key: "created_at:desc",
              value: "created_at:desc",
              label: t("ui.newest"),
            },
            {
              key: "created_at:asc",
              value: "created_at:asc",
              label: t("ui.oldest"),
            },
            { key: "name:asc", value: "name:asc", label: t("ui.nameAsc") },
          ]}
        />
      </div>
      {state.status === "loading" && (
        <Spinner statusText={t("evaluations.loading")} />
      )}
      {state.status === "error" && (
        <LoadFailure error={state.error} onRetry={retry} />
      )}
      {state.status === "ready" &&
        (state.data.evaluations.length === 0 ? (
          <PageEmptyState
            icon="article"
            message={t("evaluations.empty")}
            action={{
              label: t("evaluations.new"),
              onClick: () => go("evaluations/new"),
            }}
          />
        ) : (
          <div
            className="evaluation-table-wrap"
            role="region"
            aria-label={t("evaluations.title")}
          >
            <DataTable
              labels={labels}
              data={state.data.evaluations}
              rowKey={(row) => row.evaluation_id}
              serverPagination={{
                totalCount: state.data.total,
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
                  label: t("evaluations.name"),
                  size: "minmax(12rem, 2fr)",
                  cellRenderer: (row) => (
                    <Button
                      color="primary"
                      variant="text"
                      size="small"
                      onClick={() => go(`evaluations/${row.evaluation_id}`)}
                    >
                      {row.name}
                    </Button>
                  ),
                },
                {
                  label: t("evaluations.version"),
                  cellRenderer: (row) => row.version,
                },
                {
                  label: t("evaluations.cases"),
                  cellRenderer: (row) => row.case_count,
                },
                {
                  label: t("evaluations.completeness"),
                  cellRenderer: (row) => (
                    <StatusBadge
                      {...statusPresentation(
                        row.completeness,
                        "evaluations",
                        t,
                      )}
                    />
                  ),
                },
                {
                  label: t("evaluations.author"),
                  cellRenderer: (row) => row.author ?? row.created_by,
                },
                {
                  label: t("evaluations.created"),
                  cellRenderer: (row) =>
                    formatDate(row.created_at, i18n.language),
                },
                {
                  label: t("ui.actions"),
                  size: "12rem",
                  cellRenderer: (row) => (
                    <div className="evaluation-actions">
                      <Button
                        color="primary"
                        variant="text"
                        size="small"
                        onClick={() => go(`evaluations/${row.evaluation_id}`)}
                      >
                        {t("ui.open")}
                      </Button>
                      <Button
                        color="error"
                        variant="text"
                        size="small"
                        disabled={busy}
                        onClick={() => setSelected(row)}
                      >
                        {t("delete")}
                      </Button>
                    </div>
                  ),
                },
              ]}
            />
          </div>
        ))}
      <Dialog
        open={selected !== null}
        title={t("evaluations.deleteTitle")}
        confirmLabel={t("delete")}
        cancelLabel={t("cancel")}
        confirmColor="error"
        onConfirm={() => void remove()}
        onCancel={() => {
          if (!busy) setSelected(null);
        }}
        portalContainer={shell}
      >
        <p>{t("evaluations.deletePrompt", { name: selected?.name })}</p>
      </Dialog>
    </section>
  );
}
