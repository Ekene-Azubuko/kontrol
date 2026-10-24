"use client";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { Role } from "./types";
const AuthContext = createContext<{
  token: string;
  role: Role;
  switchRole: (role: Role) => void;
}>({ token: "", role: "resident", switchRole: () => {} });

/** Parse server errors without hiding validation failures or permission errors. */
export async function request<T>(
  path: string,
  token: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Please check the form fields and try again.",
    );
  return data as T;
}
/** Select the built-in portal identity without exposing login or account management. */
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: 1, staleTime: 2500 } },
      }),
  );
  const [role, setRole] = useState<Role>("resident");
  const [token, setToken] = useState("demo-resident");
  function switchRole(next: Role) {
    client.clear();
    setRole(next);
    setToken(`demo-${next}`);
  }
  return (
    <QueryClientProvider client={client}>
      <AuthContext.Provider value={{ token, role, switchRole }}>
        {children}
      </AuthContext.Provider>
    </QueryClientProvider>
  );
}
export function useAuth() {
  return useContext(AuthContext);
}
/** Keep each role's endpoint cache isolated and expose loading and failure states. */
export function useData<T>(path: string, enabled = true) {
  const { token } = useAuth();
  return useQuery<T>({
    queryKey: [token, path],
    queryFn: () => request<T>(path, token),
    enabled: !!token && enabled,
  });
}
/** Consume authenticated SSE invalidations with reconnect and a polling fallback. */
export function LiveUpdates() {
  const { token } = useAuth();
  const client = useQueryClient();
  useEffect(() => {
    if (!token) return;
    const abort = new AbortController();
    async function connect() {
      while (!abort.signal.aborted) {
        try {
          const response = await fetch("/api/events", {
            headers: { Authorization: `Bearer ${token}` },
            signal: abort.signal,
          });
          if (!response.ok) throw new Error("Live connection unavailable");
          const reader = response.body?.getReader();
          if (!reader) break;
          while (!abort.signal.aborted) {
            const { done } = await reader.read();
            if (done) break;
            void client.invalidateQueries();
          }
        } catch {
          if (abort.signal.aborted) break;
        }
        await new Promise((resolve) => setTimeout(resolve, 4000));
      }
    }
    void connect();
    const fallback = setInterval(() => {
      void client.invalidateQueries();
    }, 15000);
    return () => {
      abort.abort();
      clearInterval(fallback);
    };
  }, [token, client]);
  return null;
}
