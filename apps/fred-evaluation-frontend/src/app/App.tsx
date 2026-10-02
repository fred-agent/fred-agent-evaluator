import { ToastProvider, ServiceNotice } from "@fred-oss/ui";
import "../features/evaluations/layout.css";
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
        <ToastProvider
          copyLabel={t("ui.copyJson")}
          dismissLabel={t("ui.dismiss")}
        >
          {fred.status === "connecting" && <p role="status">{t("loading")}</p>}
          {fred.status === "error" && (
            <div role="alert">
              <ServiceNotice title={fred.error ?? t("errors.generic")} />
            </div>
          )}
          {fred.status === "ready" && <ApplicationRouter />}
        </ToastProvider>
      </ShellContext.Provider>
    </main>
  );
}
