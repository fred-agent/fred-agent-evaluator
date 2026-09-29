import { createRoot } from "react-dom/client";
import "@fred-oss/design-tokens/tokens.css";
import "@fred-oss/ui/styles.css";
import "./shared/i18n";
import "./shell.css";
import { App } from "./app/App";
import { loadRuntimeConfig } from "./app/config";
import { FredApplicationProvider } from "./app/providers/FredApplicationProvider";

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("Missing application root");
const root = createRoot(rootElement);
void loadRuntimeConfig()
  .then(({ hostOrigin }) => {
    root.render(
      <FredApplicationProvider hostOrigin={hostOrigin}>
        <App />
      </FredApplicationProvider>,
    );
  })
  .catch((error: unknown) => {
    const message =
      error instanceof Error ? error.message : "Invalid runtime config.json";
    root.render(
      <main role="alert" className="evaluation-shell">
        Configuration error: {message}. Mount a valid
        /apps/evaluation/config.json.
      </main>,
    );
  });
