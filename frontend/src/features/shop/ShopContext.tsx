import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { baskets, intake, sessions } from "../../api/endpoints";
import type { Basket, ConstraintDraft, Goal, Negotiation, SessionState, TraceStep } from "../../api/types";

/** Shared state for the shopping workspace. Feature panels call `useShop()` for data and actions. */
interface ShopValue {
  state: SessionState | null;
  trace: TraceStep[];
  busy: string | null;
  error: string | null;
  negotiation: Negotiation | null;
  pendingMessage: string | null;
  clearError: () => void;
  addTrace: (steps: TraceStep[] | undefined) => void;
  setBasket: (b: Basket) => void;
  run: <T extends { trace?: TraceStep[] }>(label: string, fn: () => Promise<T>, opts?: { refresh?: boolean }) => Promise<T | undefined>;
  refresh: () => Promise<void>;
  chat: (text: string) => Promise<void>;
  correct: (patch: Partial<ConstraintDraft>) => Promise<void>;
  clarify: (answer: string) => Promise<void>;
  submitForm: (form: Partial<ConstraintDraft>) => Promise<void>;
  confirm: () => Promise<void>;
  cancel: () => Promise<void>;
  build: (goal: Goal) => Promise<void>;
  negotiate: (choice: { option_id?: string; budget?: number; days?: number }) => Promise<void>;
  newSession: () => Promise<void>;
}

const ShopContext = createContext<ShopValue | null>(null);

export function ShopProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<SessionState | null>(null);
  const [trace, setTrace] = useState<TraceStep[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [negotiation, setNegotiation] = useState<Negotiation | null>(null);
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);
  const sid = state?.session.id;
  const sidRef = useRef<number | undefined>(undefined);
  sidRef.current = sid;

  const addTrace = useCallback((steps: TraceStep[] | undefined) => {
    if (steps?.length) setTrace((t) => [...t, ...steps.filter((s) => !t.some((x) => x.id === s.id))]);
  }, []);

  useEffect(() => {
    sessions
      .current()
      .then(({ trace: t, ...s }) => {
        setState(s);
        addTrace(t);
      })
      .catch((e) => setError(e.message));
  }, [addTrace]);

  const refresh = useCallback(async () => {
    if (sidRef.current) setState(await sessions.get(sidRef.current));
  }, []);

  const run = useCallback(
    async <T extends { trace?: TraceStep[] }>(label: string, fn: () => Promise<T>, opts: { refresh?: boolean } = {}) => {
      setBusy(label);
      setError(null);
      try {
        const result = await fn();
        addTrace(result.trace);
        if (opts.refresh !== false) await refresh();
        return result;
      } catch (e) {
        setError((e as Error).message);
        return undefined;
      } finally {
        setBusy(null);
      }
    },
    [addTrace, refresh],
  );

  const requestId = state?.intake?.request_id;

  const value = useMemo<ShopValue>(
    () => ({
      state,
      trace,
      busy,
      error,
      negotiation,
      pendingMessage,
      clearError: () => setError(null),
      addTrace,
      run,
      refresh,
      setBasket: (b) => setState((s) => (s ? { ...s, basket: b } : s)),
      chat: async (text) => {
        if (!sid) return;
        setPendingMessage(text);
        const r = await run("Your shopper is reading that", () => sessions.chat(sid, text), { refresh: false });
        setPendingMessage(null);
        if (r) {
          setState(r.state);
          if (r.response.kind === "intake" || r.response.kind === "edit") setNegotiation(null);
          const edit = r.response.edit as { status?: string; suggestions?: Negotiation["options"]; message?: string } | undefined;
          if (edit?.status === "conflict" && edit.suggestions?.length) {
            setNegotiation({ message: edit.message ?? "", options: edit.suggestions, blocked_roles: [], budget: null, days: 0, person_meals: 0, shortfall: null });
          }
        }
      },
      correct: async (patch) => {
        if (requestId) await run("Revising your constraints", () => intake.correct(requestId, patch));
      },
      clarify: async (answer) => {
        if (requestId) await run("Updating your request", () => intake.clarify(requestId, answer));
      },
      submitForm: async (form) => {
        if (requestId) await run("Saving the form", () => intake.form(requestId, form));
      },
      confirm: async () => {
        if (requestId) await run("Saving your constraints", () => intake.confirm(requestId));
      },
      cancel: async () => {
        if (requestId) await run("Cancelling", () => intake.cancel(requestId));
      },
      build: async (goal) => {
        if (!sid) return;
        const r = await run("Pricing, safety-checking and optimising your basket", () => baskets.build(sid, goal));
        if (r) setNegotiation(r.status === "infeasible" ? r.negotiation : null);
      },
      negotiate: async (choice) => {
        if (!sid) return;
        const r = await run("Rebuilding with your trade-off", () => baskets.negotiate(sid, choice));
        if (r) setNegotiation(r.status === "infeasible" ? r.negotiation : null);
      },
      newSession: async () => {
        const r = await run("Starting a new shop", () => sessions.create(), { refresh: false });
        if (r) {
          const { trace: _t, ...s } = r;
          void _t;
          setState(s);
          setNegotiation(null);
        }
      },
    }),
    [state, trace, busy, error, negotiation, pendingMessage, addTrace, run, refresh, sid, requestId],
  );

  return <ShopContext.Provider value={value}>{children}</ShopContext.Provider>;
}

export function useShop(): ShopValue {
  const ctx = useContext(ShopContext);
  if (!ctx) throw new Error("useShop must be used inside <ShopProvider>");
  return ctx;
}
