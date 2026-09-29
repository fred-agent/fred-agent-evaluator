import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  createFredApplicationClient,
  type FredApplicationClient,
  type FredApplicationContext,
} from "@fred-oss/iframe-sdk";
import i18n, { normalizeLocale } from "../../shared/i18n";
import { APPLICATION_ID } from "../applicationId";

type ConnectionStatus = "connecting" | "ready" | "error";
type ClientFactory = typeof createFredApplicationClient;

interface FredState {
  status: ConnectionStatus;
  error: string | null;
  context: FredApplicationContext | null;
  subPath: string;
  navigate: (path: string) => void;
  request: FredApplicationClient["request"];
}

const FredContext = createContext<FredState | null>(null);

/** Keep FRED subpaths relative; consumers navigate with "details" or "" for root. */
export function FredApplicationProvider({
  hostOrigin,
  clientFactory = createFredApplicationClient,
  children,
}: {
  hostOrigin: string;
  clientFactory?: ClientFactory;
  children: ReactNode;
}) {
  const clientRef = useRef<FredApplicationClient | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [context, setContext] = useState<FredApplicationContext | null>(null);
  const [subPath, setSubPath] = useState("");

  useEffect(() => {
    let active = true;
    let unsubscribeContext: (() => void) | undefined;
    let unsubscribeRoute: (() => void) | undefined;
    const client = clientFactory({
      hostOrigin,
      applicationId: APPLICATION_ID,
    });
    clientRef.current = client;
    const acceptContext = (next: FredApplicationContext) => {
      if (!active) return;
      setContext(next);
      setSubPath(next.route.subPath);
      void i18n.changeLanguage(normalizeLocale(next.locale));
    };
    void client
      .connect()
      .then((initial) => {
        if (!active) return;
        acceptContext(initial);
        unsubscribeContext = client.onContext(acceptContext);
        unsubscribeRoute = client.onRoute((route) => {
          if (active) setSubPath(route.subPath);
        });
        // A context can arrive between connect() and the subscriptions.
        if (client.context) acceptContext(client.context);
        setStatus("ready");
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(
          reason instanceof Error
            ? reason.message
            : "Unable to connect to FRED",
        );
        setStatus("error");
      });
    return () => {
      active = false;
      unsubscribeContext?.();
      unsubscribeRoute?.();
      client.dispose();
      if (clientRef.current === client) clientRef.current = null;
    };
  }, [hostOrigin, clientFactory]);

  const navigate = useCallback((path: string) => {
    if (path.startsWith("/"))
      throw new Error("Expected an SDK-relative subpath");
    const client = clientRef.current;
    if (!client) throw new Error("FRED connection is unavailable");
    client.navigate(path);
    setSubPath(path);
  }, []);
  const request = useCallback<FredApplicationClient["request"]>(
    (path, init) => {
      const client = clientRef.current;
      if (!client)
        return Promise.reject(new Error("FRED connection is unavailable"));
      return client.request(path, init);
    },
    [],
  );
  const state = useMemo(
    () => ({ status, error, context, subPath, navigate, request }),
    [status, error, context, subPath, navigate, request],
  );
  return <FredContext.Provider value={state}>{children}</FredContext.Provider>;
}

export function useFredApplication(): FredState {
  const state = useContext(FredContext);
  if (!state) throw new Error("FredApplicationProvider is required");
  return state;
}
