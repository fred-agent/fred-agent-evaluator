import { useCallback, useEffect, useState } from "react";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Button } from "@fred-oss/ui";
import { useFredApplication } from "./providers/FredApplicationProvider";
import { EvaluationsPage } from "../features/evaluations/EvaluationsPage";
import { EvaluationCreatePage } from "../features/evaluations/EvaluationCreatePage";
import { EvaluationPage } from "../features/evaluations/EvaluationPage";
import { RunCreatePage } from "../features/evaluations/RunCreatePage";
import { RunDetailPage } from "../features/evaluations/RunDetailPage";

/**
 * Navigate inside the application: `path` is relative to it ("" for the list,
 * "runs/<id>"...). The host's route follows, so reloads and links land here.
 */
export function useAppNavigate() {
  const navigateMemory = useNavigate();
  const { navigate: navigateHost } = useFredApplication();
  return useCallback(
    (path: string) => {
      navigateMemory(`/${path}`);
      navigateHost(path);
    },
    [navigateMemory, navigateHost],
  );
}

function NotFound() {
  const { t } = useTranslation();
  const go = useAppNavigate();
  return (
    <section>
      <h1>{t("unknownRoute")}</h1>
      <div>
        <Button
          color="primary"
          variant="outlined"
          size="small"
          onClick={() => go("")}
        >
          {t("back")}
        </Button>
      </div>
    </section>
  );
}

function RunWithCase() {
  const { runId, caseId } = useParams();
  return runId && caseId ? (
    <RunDetailPage key={runId} runId={runId} caseId={caseId} />
  ) : (
    <NotFound />
  );
}

function WithParam({
  name,
  render,
}: {
  name: string;
  render: (value: string) => React.ReactNode;
}) {
  const value = useParams()[name];
  return value ? <>{render(value)}</> : <NotFound />;
}

/** Keep the in-memory route on the host's subpath, without echoing it back. */
function RouteContent() {
  const { subPath, context } = useFredApplication();
  const navigateMemory = useNavigate();
  const location = useLocation();
  const reactPath = subPath === "" ? "/" : `/${subPath}`;

  useEffect(() => {
    if (location.pathname !== reactPath)
      navigateMemory(reactPath, { replace: true });
  }, [reactPath, location.pathname, navigateMemory]);

  // Remount everything when the host switches team.
  return (
    <Routes key={context?.team.id}>
      <Route path="/" element={<EvaluationsPage />} />
      <Route path="/evaluations/new" element={<EvaluationCreatePage />} />
      <Route
        path="/evaluations/:evaluationId"
        element={
          <WithParam
            name="evaluationId"
            render={(id) => <EvaluationPage key={id} evaluationId={id} />}
          />
        }
      />
      <Route
        path="/evaluations/:evaluationId/runs/new"
        element={
          <WithParam
            name="evaluationId"
            render={(id) => <RunCreatePage key={id} evaluationId={id} />}
          />
        }
      />
      <Route
        path="/runs/:runId"
        element={
          <WithParam
            name="runId"
            render={(id) => <RunDetailPage key={id} runId={id} />}
          />
        }
      />
      <Route path="/runs/:runId/cases/:caseId" element={<RunWithCase />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

export function ApplicationRouter() {
  const { subPath } = useFredApplication();
  // Start on the host's route: a deep link must not render (and load) the
  // list first. Later host moves are followed by RouteContent.
  const [initial] = useState(() => [subPath === "" ? "/" : `/${subPath}`]);
  return (
    <MemoryRouter initialEntries={initial}>
      <RouteContent />
    </MemoryRouter>
  );
}
