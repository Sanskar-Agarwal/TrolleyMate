// One function per backend endpoint, grouped by feature (and by owner: see docs/TEAM_GUIDE.md).
import { api } from "./client";
import type {
  AuditEntry,
  Basket,
  ChatMessage,
  Comparison,
  ConstraintDraft,
  EscalationCase,
  Explanation,
  Goal,
  Household,
  IntakeState,
  LlmStatus,
  MealPlan,
  Negotiation,
  Nutrition,
  NutritionRepair,
  PreferenceKind,
  SessionState,
  StoredPreference,
  Substitution,
  TimingAdvice,
  User,
  WithTrace,
} from "./types";

type BuildResult = WithTrace<
  | { status: "ok"; basket: Basket }
  | { status: "infeasible"; negotiation: Negotiation }
  | { status: "retryable"; reason: "timeout" | "solver_error"; message: string }
  | { status: "cancelled"; message: string }
>;

// --- Auth & system (Platform) ------------------------------------------------
export const auth = {
  login: (email: string, password: string) => api<{ token: string; user: User }>("/auth/login", { body: { email, password } }),
  register: (body: { display_name: string; email: string; password: string; household_name?: string }) =>
    api<{ token: string; user: User }>("/auth/register", { body }),
  me: () => api<User>("/auth/me"),
  demoAccounts: () => api<{ email: string; display_name: string; role: string }[]>("/auth/demo-accounts"),
};
export const system = {
  llm: () => api<LlmStatus>("/system/llm"),
};

// --- Sessions & chat (Intake / supervisor) ------------------------------------
export const sessions = {
  current: () => api<WithTrace<SessionState>>("/sessions/current"),
  create: () => api<WithTrace<SessionState>>("/sessions", { body: {} }),
  get: (id: number) => api<SessionState>(`/sessions/${id}`),
  chat: (id: number, text: string) =>
    api<WithTrace<{ response: { intent: string; kind: string; reply: string } & Record<string, unknown>; state: SessionState }>>(
      `/sessions/${id}/chat`,
      { body: { text } },
    ),
};

// --- UC-01 Intake (Sanskar) ----------------------------------------------------
type IntakeResult = WithTrace<{ intake: IntakeState; constraints?: SessionState["constraints"] }>;
export const intake = {
  submit: (sessionId: number, text: string) => api<IntakeResult>(`/sessions/${sessionId}/requests`, { body: { text } }),
  clarify: (requestId: number, text: string) => api<IntakeResult>(`/requests/${requestId}/clarify`, { body: { text } }),
  correct: (requestId: number, patch: Partial<ConstraintDraft>, text?: string) =>
    api<IntakeResult>(`/requests/${requestId}/correct`, { body: { patch, text } }),
  form: (requestId: number, form: Partial<ConstraintDraft>) => api<IntakeResult>(`/requests/${requestId}/form`, { body: form }),
  confirm: (requestId: number) => api<IntakeResult>(`/requests/${requestId}/confirm`, { body: {} }),
  cancel: (requestId: number) => api<IntakeResult>(`/requests/${requestId}/cancel`, { body: {} }),
};

// --- UC-02 / UC-03 Baskets & negotiation (Sanskar, Peter) ----------------------
export const baskets = {
  goals: () => api<{ id: Goal; label: string }[]>("/goals"),
  build: (sessionId: number, goal: Goal, operationId?: string) =>
    api<BuildResult>(`/sessions/${sessionId}/basket`, { body: { goal, operation_id: operationId } }),
  negotiate: (sessionId: number, choice: { option_id?: string; budget?: number; days?: number; goal?: Goal }, operationId?: string) =>
    api<BuildResult>(`/sessions/${sessionId}/negotiate`, { body: { ...choice, operation_id: operationId } }),
  cancelBuild: (sessionId: number, operationId: string) =>
    api<WithTrace<{ status: "cancellation_requested" | "already_finished" | "not_running"; outcome?: "committed" | "cancelled" | "failed" }>>(
      `/sessions/${sessionId}/basket-builds/${operationId}/cancel`, { body: {} },
    ),
  cancelNegotiation: (sessionId: number) =>
    api<WithTrace<{ status: "cancelled"; basket: Basket | null }>>(`/sessions/${sessionId}/negotiate/cancel`, { body: {} }),
  get: (id: number) => api<Basket>(`/baskets/${id}`),
  accept: (id: number) => api<WithTrace<{ basket: Basket }>>(`/baskets/${id}/accept`, { body: {} }),
};

// --- UC-04 Substitution & 1.2.6 buy timing (Peter) -------------------------------
export const substitutions = {
  propose: (basketId: number, itemId: number, reason = "user_requested") =>
    api<WithTrace<{ substitution: Substitution; basket: Basket }>>(`/baskets/${basketId}/items/${itemId}/substitute`, { body: { reason } }),
  accept: (id: number) => api<WithTrace<{ substitution: Substitution; basket: Basket }>>(`/substitutions/${id}/accept`, { body: {} }),
  reject: (id: number) => api<WithTrace<{ substitution: Substitution; basket: Basket }>>(`/substitutions/${id}/reject`, { body: {} }),
};
export const timing = {
  advice: (basketId: number) =>
    api<WithTrace<{ advice: TimingAdvice[]; demo_history: boolean; history_note: string | null }>>(`/baskets/${basketId}/buy-timing`),
};

// --- UC-05 Pricing & UC-09 editing (Chester) ------------------------------------
export const pricing = {
  compare: (basketId: number, baselineId?: number) =>
    api<WithTrace<Comparison>>(`/baskets/${basketId}/comparison${baselineId ? `?baseline_id=${baselineId}` : ""}`),
  retailers: () => api<{ id: number; name: string; region: string; source: string }[]>("/retailers"),
};
export const editing = {
  edit: (basketId: number, text: string) =>
    api<WithTrace<{ status: "ok" | "clarify" | "conflict"; basket?: Basket; applied?: string[]; conflicts?: string[]; question?: string; message?: string; suggestions?: unknown[] }>>(
      `/baskets/${basketId}/edit`,
      { body: { text } },
    ),
};

// --- UC-08 Meal plans (Sanskar) -------------------------------------------------
export const mealPlans = {
  generate: (basketId: number) => api<WithTrace<{ meal_plan: MealPlan }>>(`/baskets/${basketId}/meal-plan`, { body: {} }),
};

// --- UC-06 compliance & 1.2.12 preferences (Reyon) -------------------------------
export const compliance = {
  verify: (basketId: number) => api<WithTrace<{ basket: Basket }>>(`/baskets/${basketId}/verify`, { body: {} }),
  nutrition: (basketId: number) => api<WithTrace<{ nutrition: Nutrition; repairs: NutritionRepair[] }>>(`/baskets/${basketId}/nutrition`),
  acceptGap: (basketId: number, nutrients: string[], note: string) =>
    api<WithTrace<{ basket: Basket }>>(`/baskets/${basketId}/nutrition/exceptions`, { body: { nutrients, note } }),
};
type PreferencesChanged = WithTrace<{ household: Household; preferences: StoredPreference[] }>;
export const preferences = {
  list: () => api<StoredPreference[]>("/households/me/preferences"),
  add: (kind: PreferenceKind, value: string) => api<PreferencesChanged>("/households/me/preferences", { body: { kind, value } }),
  update: (id: number, kind: PreferenceKind, value: string) =>
    api<PreferencesChanged>(`/households/me/preferences/${id}`, { method: "PUT", body: { kind, value } }),
  remove: (id: number) => api<PreferencesChanged>(`/households/me/preferences/${id}`, { method: "DELETE" }),
};

// --- UC-10 households, UC-07 explain/audit, UC-06 ext review (Maaz) ----------------
export interface MemberInput {
  name: string;
  age_group: string;
  restrictions: { restriction: string; severity: string }[];
}
export const households = {
  me: () => api<Household>("/households/me"),
  vocabulary: () => api<{ id: string; label: string; kind: string }[]>("/dietary/restrictions"),
  rename: (name: string) => api<WithTrace<{ household: Household }>>("/households/me", { method: "PUT", body: { name } }),
  addMember: (m: MemberInput) => api<WithTrace<{ household: Household }>>("/households/me/members", { body: m }),
  updateMember: (id: number, m: MemberInput) =>
    api<WithTrace<{ household: Household }>>(`/households/me/members/${id}`, { method: "PUT", body: m }),
  removeMember: (id: number) => api<WithTrace<{ household: Household }>>(`/households/me/members/${id}`, { method: "DELETE" }),
};
export const explain = {
  basket: (basketId: number) => api<WithTrace<Explanation>>(`/baskets/${basketId}/explain`),
  item: (basketId: number, itemId: number) => api<WithTrace<Explanation>>(`/baskets/${basketId}/items/${itemId}/explain`),
};
export const escalations = {
  queue: (status?: string) => api<WithTrace<{ cases: EscalationCase[] }>>(`/escalations${status ? `?status=${status}` : ""}`),
  get: (id: number) => api<EscalationCase>(`/escalations/${id}`),
  begin: (id: number) => api<WithTrace<{ case: EscalationCase }>>(`/escalations/${id}/begin`, { body: {} }),
  requestInfo: (id: number, question: string) =>
    api<WithTrace<{ case: EscalationCase }>>(`/escalations/${id}/request-info`, { body: { question } }),
  resolve: (id: number, decision: "passed" | "failed", note: string) =>
    api<WithTrace<{ case: EscalationCase }>>(`/escalations/${id}/resolve`, { body: { decision, note } }),
  reviewers: () => api<{ id: number; display_name: string; role: string }[]>("/escalations/reviewers"),
  assign: (id: number, reviewerId: number) =>
    api<WithTrace<{ case: EscalationCase }>>(`/escalations/${id}/assign`, { body: { reviewer_id: reviewerId } }),
};
export const audit = {
  list: (params: { agent?: string; session_id?: number; basket_id?: number; limit?: number } = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)]));
    return api<AuditEntry[]>(`/audit${q.size ? `?${q}` : ""}`);
  },
  stats: () =>
    api<{ per_agent: Record<string, number>; per_provider: Record<string, number>; open_cases: number; llm: LlmStatus; policy: Record<string, unknown> }>(
      "/audit/stats",
    ),
};

export type { ChatMessage };
