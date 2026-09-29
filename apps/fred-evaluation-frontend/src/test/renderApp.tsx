import { render } from "@testing-library/react";
import type { FredApplicationRequestInit } from "@fred-oss/iframe-sdk";
import { App } from "../app/App";
import { FredApplicationProvider } from "../app/providers/FredApplicationProvider";
import { fakeFredClient, initialContext } from "./fakeFredClient";

type Handler = (
  init: FredApplicationRequestInit | undefined,
  path: string,
) => Response | Promise<Response>;

/**
 * Renders the application inside a fake Fred host, on `subPath`, answering
 * each request with the handler of the first matching "METHOD path-prefix".
 * An unmatched request is a 404, so a test sees exactly the calls it expects.
 */
export function renderApp(routes: Record<string, Handler>, subPath = "") {
  const fake = fakeFredClient(
    (path, init) => {
      const method = init?.method ?? "GET";
      const bare = path.split("?")[0];
      const key = Object.keys(routes).find((candidate) => {
        const [m, p] = candidate.split(" ");
        return m === method && bare === p;
      });
      return key
        ? routes[key](init, path)
        : Response.json({ detail: "no route" }, { status: 404 });
    },
    { ...initialContext, route: { ...initialContext.route, subPath } },
  );
  const view = render(
    <FredApplicationProvider
      hostOrigin="https://fred.example"
      clientFactory={() => fake.client}
    >
      <App />
    </FredApplicationProvider>,
  );
  return { fake, view };
}

export const ok = (body: unknown) => () => Response.json(body);
