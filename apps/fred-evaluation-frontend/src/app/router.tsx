import { useEffect } from "react";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Button } from "@fred-oss/ui";
import { useFredApplication } from "./providers/FredApplicationProvider";
import { EvaluationsPage } from "../features/evaluations/EvaluationsPage";

/** Adapt Fred's relative subpaths to React Router paths without echoing host routes. */
function RouteContent() {
  const { t } = useTranslation();
  const { subPath, navigate: navigateHost, context } = useFredApplication();
  const navigateMemory = useNavigate();
  const location = useLocation();
  const reactPath = subPath === "" ? "/" : `/${subPath}`;

  useEffect(() => {
    if (location.pathname !== reactPath)
      navigateMemory(reactPath, { replace: true });
  }, [reactPath, location.pathname, navigateMemory]);

  // React uses "/details"; the SDK must receive "details" (or "" for root).
  const childNavigate = (path: string) => {
    navigateMemory(path);
    navigateHost(path.slice(1));
  };

  return (
    <Routes>
      <Route path="/" element={<EvaluationsPage key={context?.team.id} />} />
      <Route
        path="*"
        element={
          <section>
            <h1>{t("unknownRoute")}</h1>
            <Button
              color="primary"
              variant="outlined"
              size="small"
              onClick={() => childNavigate("/")}
            >
              {t("back")}
            </Button>
          </section>
        }
      />
    </Routes>
  );
}

export function ApplicationRouter() {
  return (
    <MemoryRouter>
      <RouteContent />
    </MemoryRouter>
  );
}
