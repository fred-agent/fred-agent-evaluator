import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ApplicationRouter } from "./router";
import { useFredApplication } from "./providers/FredApplicationProvider";
import { ShellContext } from "./shell";

/** Render the feature only after Fred supplies trusted application context. */
export function App() {
  const { t } = useTranslation();
  const fred = useFredApplication();
  const [shell, setShell] = useState<HTMLElement | null>(null);

  return (
    <main
      ref={setShell}
      className="fred-ui evaluation-shell"
      data-theme={fred.context?.theme ?? "light"}
    >
      <ShellContext.Provider value={shell}>
        {fred.status === "connecting" && <p role="status">{t("loading")}</p>}
        {fred.status === "error" && <p role="alert">{fred.error}</p>}
        {fred.status === "ready" && <ApplicationRouter />}
      </ShellContext.Provider>
    </main>
  );
}
