import { vi } from "vitest";
import type {
  FredApplicationClient,
  FredApplicationContext,
  FredApplicationRequestInit,
  FredApplicationRoute,
} from "@fred-oss/iframe-sdk";

export const initialContext: FredApplicationContext = {
  team: { id: "team-one", name: "Team One", isPersonal: false },
  route: { basePath: "/apps/evaluation", subPath: "" },
  locale: "en",
  theme: "dark",
};

/** A Fred host stand-in: records requests, emits context and route changes. */
export function fakeFredClient(
  respond: (
    path: string,
    init?: FredApplicationRequestInit,
  ) => Response | Promise<Response>,
  start: FredApplicationContext = initialContext,
) {
  let current = start;
  const contexts = new Set<(context: FredApplicationContext) => void>();
  const routes = new Set<(route: FredApplicationRoute) => void>();
  const request = vi.fn((path: string, init?: FredApplicationRequestInit) =>
    Promise.resolve(respond(path, init)),
  );
  const client: FredApplicationClient = {
    get context() {
      return current;
    },
    connect: vi.fn().mockResolvedValue(start),
    onContext: vi.fn((listener) => {
      contexts.add(listener);
      return () => contexts.delete(listener);
    }),
    onRoute: vi.fn((listener) => {
      routes.add(listener);
      return () => routes.delete(listener);
    }),
    navigate: vi.fn(),
    openChat: vi.fn(),
    request,
    dispose: vi.fn(),
  };
  return {
    client,
    request,
    contexts,
    routes,
    emitContext(next: FredApplicationContext) {
      current = next;
      for (const listener of contexts) listener(next);
    },
    emitRoute(subPath: string) {
      for (const listener of routes) listener({ subPath });
    },
  };
}
