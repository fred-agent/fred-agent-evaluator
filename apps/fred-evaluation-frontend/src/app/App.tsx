import { useTranslation } from "react-i18next";
import { ApplicationRouter } from "./router";
import { useFredApplication } from "./providers/FredApplicationProvider";

/** Render the feature only after Fred supplies trusted application context. */
export function App() {
  const { t } = useTranslation();
  const fred = useFredApplication();

  return (
    <main
      className="fred-ui evaluation-shell"
      data-theme={fred.context?.theme ?? "light"}
    >
      {fred.status === "connecting" && <p role="status">{t("loading")}</p>}
      {fred.status === "error" && <p role="alert">{fred.error}</p>}
      {fred.status === "ready" && <ApplicationRouter />}
    </main>
  );
}
