import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  DataTable,
  InlineDrawer,
  PageEmptyState,
  Spinner,
  StatusBadge,
} from "@fred-oss/ui";
import { useLoad } from "../../shared/api/useLoad";
import { useAppNavigate } from "../../app/router";
import { useEvaluationApi } from "./useEvaluationApi";
import { LoadFailure } from "./LoadFailure";
import { formatScore, statusPresentation, isTerminal } from "./presentation";
import { useTableLabels } from "./ListControls";

export function RunPreview({
  runId,
  onClose,
}: {
  runId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const api = useEvaluationApi();
  const go = useAppNavigate();
  const labels = useTableLabels();
  const load = useCallback(async () => {
    const [run, cases] = await Promise.all([
      api.getRun(runId),
      api.listRunCases(runId),
    ]);
    return { run, ...cases };
  }, [api, runId]);
  const { state, retry } = useLoad(load, (data) =>
    isTerminal(data.run.operational_state) ? null : 3000,
  );
  return (
    <InlineDrawer
      closeLabel={t("ui.close")}
      open
      onClose={onClose}
      title={t("ui.preview")}
      width="min(48rem, 100vw)"
    >
      {state.status === "loading" && <Spinner statusText={t("loadingPage")} />}
      {state.status === "error" && (
        <LoadFailure error={state.error} onRetry={retry} />
      )}
      {state.status === "ready" &&
        (state.data.cases.length === 0 ? (
          <PageEmptyState icon="article" message={t("cases.empty")} />
        ) : (
          <DataTable
            labels={labels}
            data={state.data.cases}
            rowKey={(row) => row.case_id}
            columns={[
              {
                label: t("cases.input"),
                size: "2fr",
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
                    {row.input}
                  </Button>
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
                label: t("cases.metrics"),
                cellRenderer: (row) => (
                  <div>
                    {row.metrics.map((metric) => (
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
        ))}
    </InlineDrawer>
  );
}
