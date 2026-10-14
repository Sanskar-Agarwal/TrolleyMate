import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { baskets, intake, sessions } from "../../api/endpoints";
import type { Basket, ConstraintDraft, Goal, Negotiation, SessionState, TraceStep } from "../../api/types";
import { useToast } from "../../components/Toast";
import { money } from "../../lib/format";

export type ShopView = "basket" | "prices" | "meals" | "timing";
export const FOCUS_CHAT_EVENT = "trolleymate:focus-chat";

type Tone = "ok" | "warn" | "info";
interface RunOptions<T> {
  refresh?: boolean;
  /** Toast to show on success; return undefined for none. */
  toast?: (result: T) => [string, Tone?] | undefined;
}

/** Shared state for the shopping workspace. Feature panels call `useShop()` for data and actions. */
interface ShopValue {
  state: SessionState | null;
  trace: TraceStep[];
  busy: string | null;
  error: string | null;
  negotiation: Negotiation | null;
  pendingMessage: string | null;
  view: ShopView;
  setView: (v: ShopView) => void;
  focusChat: (prefill?: string) => void;
  clearError: () => void;
  addTrace: (steps: TraceStep[] | undefined) => void;
  setBasket: (b: Basket) => void;
  run: <T extends { trace?: TraceStep[] }>(label: string, fn: () => Promise<T>, opts?: RunOptions<T>) => Promise<T | undefined>;
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

const BUILD_TOAST = (r: { status: string; basket?: Basket }): [string, Tone] =>
  r.status === "ok" && r.basket
    ? [`Basket ready: ${r.basket.items.length} items for ${money(r.basket.total)}`, "ok"]
    : ["That doesn't fit. Pick a trade-off below.", "warn"];

export function ShopProvider({ children }: { children: React.ReactNode }) {
  const toast = useToast();
  const [state, setState] = useState<SessionState | null>(null);
  const [trace, setTrace] = useState<TraceStep[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [negotiation, setNegotiation] = useState<Negotiation | null>(null);
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);
  const [view, setView] = useState<ShopView>("basket");
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
    async <T extends { trace?: TraceStep[] }>(label: string, fn: () => Promise<T>, opts: RunOptions<T> = {}) => {
      setBusy(label);
      setError(null);
      try {
        const result = await fn();
        addTrace(result.trace);
        if (opts.refresh !== false) await refresh();
        const t = opts.toast?.(result);
        if (t) toast(t[0], t[1]);
        return result;
      } catch (e) {
        setError((e as Error).message);
        return undefined;
      } finally {
        setBusy(null);
      }
    },
    [addTrace, refresh, toast],
  );

  const focusChat = useCallback((prefill?: string) => {
    window.dispatchEvent(new CustomEvent(FOCUS_CHAT_EVENT, { detail: prefill }));
  }, []);

  const requestId = state?.intake?.request_id;

  const value = useMemo<ShopValue>(
    () => ({
      state,
      trace,
      busy,
      error,
      negotiation,
      pendingMessage,
      view,
      setView,
      focusChat,
      clearError: () => setError(null),
      addTrace,
      run,
      refresh,
      setBasket: (b) => setState((s) => (s ? { ...s, basket: b } : s)),
      chat: async (text) => {
        if (!sid) return;
        setPendingMessage(text);
        const r = await run("Your shopper is reading that", () => sessions.chat(sid, text), {
          refresh: false,
          toast: (res) => {
            const kind = res.response.kind;
            const edit = res.response.edit as { status?: string } | undefined;
            if (kind === "edit" && edit?.status === "ok") return ["Basket updated"];
            if (kind === "meal_plan") return ["Meal plan ready"];
            return undefined;
          },
        });
        setPendingMessage(null);
        if (r) {
          setState(r.state);
          const kind = r.response.kind;
          if (kind === "intake" || kind === "edit") setNegotiation(null);
          if (kind === "meal_plan") setView("meals");
          if (kind === "compare") setView("prices");
          const edit = r.response.edit as { status?: string; suggestions?: Negotiation["options"]; message?: string } | undefined;
          if (edit?.status === "conflict" && edit.suggestions?.length) {
            setNegotiation({ message: edit.message ?? "", options: edit.suggestions, blocked_roles: [], budget: null, days: 0, person_meals: 0, shortfall: null });
          }
        }
      },
      correct: async (patch) => {
        if (requestId) await run("Revising your details", () => intake.correct(requestId, patch), { toast: () => ["Correction applied"] });
      },
      clarify: async (answer) => {
        if (requestId) await run("Updating your request", () => intake.clarify(requestId, answer));
      },
      submitForm: async (form) => {
        if (requestId) await run("Saving the form", () => intake.form(requestId, form), { toast: () => ["Form saved"] });
      },
      confirm: async () => {
        if (requestId) await run("Saving your details", () => intake.confirm(requestId), { toast: () => ["Saved. Now pick what matters most."] });
      },
      cancel: async () => {
        if (requestId) await run("Cancelling", () => intake.cancel(requestId), { toast: () => ["Request cancelled", "info"] });
      },
      build: async (goal) => {
        if (!sid) return;
        const r = await run("Building your basket", () => baskets.build(sid, goal), { toast: BUILD_TOAST });
        if (r) {
          setNegotiation(r.status === "infeasible" ? r.negotiation : null);
          setView("basket");
        }
      },
      negotiate: async (choice) => {
        if (!sid) return;
        const r = await run("Building your basket", () => baskets.negotiate(sid, choice), { toast: BUILD_TOAST });
        if (r) setNegotiation(r.status === "infeasible" ? r.negotiation : null);
      },
      newSession: async () => {
        const r = await run("Starting a new shop", () => sessions.create(), { refresh: false, toast: () => ["New shop started", "info"] });
        if (r) {
          const { trace: _t, ...s } = r;
          void _t;
          setState(s);
          setNegotiation(null);
          setView("basket");
        }
      },
    }),
    [state, trace, busy, error, negotiation, pendingMessage, view, focusChat, addTrace, run, refresh, sid, requestId],
  );

  return <ShopContext.Provider value={value}>{children}</ShopContext.Provider>;
}

export function useShop(): ShopValue {
  const ctx = useContext(ShopContext);
  if (!ctx) throw new Error("useShop must be used inside <ShopProvider>");
  return ctx;
}
