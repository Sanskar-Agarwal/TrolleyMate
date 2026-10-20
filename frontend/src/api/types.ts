// Shapes returned by the FastAPI backend (see backend/app/api/common.py).
// Keep in sync when a serializer changes.

export type Role = "shopper" | "dietitian" | "founder";
export type Goal = "lowest_cost" | "best_nutrition" | "least_waste" | "fastest_cook" | "balanced";

export interface User {
  id: number;
  email: string;
  display_name: string;
  role: Role;
  registration_no?: string | null;
  specialisation?: string | null;
}

export interface TraceStep {
  id: number;
  agent: "personal_shopper" | "market_analyst" | "nutrition_compliance" | "technical_manager" | "human_reviewer" | string;
  agent_name: string;
  action: string;
  decision: string;
  confidence: number | null;
  provider: string;
  fell_back: boolean;
  llm: boolean;
  at: string;
}

export interface Restriction {
  restriction: string;
  severity: string;
  label?: string;
  source?: string;
  locked?: boolean;
  members?: string[];
}

export interface ConstraintDraft {
  budget?: number | null;
  household_size?: number | null;
  meals_per_day?: number | null;
  days?: number | null;
  restrictions?: Restriction[];
  nutritional_targets?: { nutrient: string; minimum_per_day: number }[];
  preferences?: string[];
  goal_hint?: Goal | null;
  assumptions?: string[];
}

export interface IntakeState {
  request_id: number;
  raw_text: string;
  status: "draft" | "confirmed" | "cancelled" | "infeasible";
  stage: string;
  mode: "text" | "form";
  correction_count: number;
  max_corrections: number;
  draft: ConstraintDraft;
  questions: { field: string; question: string }[];
  missing_fields: string[];
  assumptions: string[];
}

export interface BasketItem {
  id: number;
  product: {
    id: number;
    name: string;
    brand: string;
    category: string;
    pack_size: number;
    unit: string;
    servings: number;
    tags: string[];
    perishable: boolean;
  };
  retailer: { id: number; name: string };
  quantity: number;
  pack_price: number;
  line_total: number;
  unit_price_label: string | null;
  on_special: boolean;
  compliance: "compliant" | "violation" | "uncertain" | "unchecked";
  withheld: boolean;
  rationale: string;
}

export interface Nutrition {
  adequate: boolean;
  provided: Record<string, number>;
  required: Record<string, number>;
  gaps: { nutrient: string; required: number; provided: number; short_by: number }[];
  suggestions: string[];
  // Added by the verdict contract (KAN-19, KAN-21); absent on baskets built before it.
  coverage?: { nutrient: string; required: number; provided: number; coverage_pct: number; met: boolean; accepted?: boolean }[];
  targets?: string;
  exceptions?: NutritionException[];
}

/** A nutrition gap the shopper explicitly accepted (1.2.11). */
export interface NutritionException {
  nutrient: string;
  short_by: number;
  accepted_by: string;
  accepted_by_id: number | null;
  accepted_at: string;
  note: string;
}

/** A compliant product that would close (part of) a gap. Suggested, never added automatically. */
export interface NutritionRepair {
  nutrient: string;
  product_id: number;
  product: string;
  quantity: number;
  adds: number;
  closes_gap: boolean;
  cost: number;
  retailer: string;
  within_budget: boolean;
}

export type PreferenceKind = "dislike" | "like" | "brand" | "avoid_brand";

/** A remembered taste or shopping preference and what it does to later baskets (1.2.12). */
export interface StoredPreference {
  id: number;
  kind: PreferenceKind;
  value: string;
  source: string;
  label: string;
  effect: "avoid" | "favour" | "unknown";
  /** applied: an avoid preference leaves matches out of new baskets; a favour one wins them close calls ·
   *  overridden: every match breaks a mandatory restriction · no_match: nothing in the catalogue */
  status: "applied" | "overridden" | "no_match";
  matches: string[];
  match_count: number;
  blocked: { product: string; reason: string }[];
  hint: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface CaseBrief {
  id: number;
  status: string;
  product: string;
  reason: string;
  resolution: string | null;
  assigned_to: string | null;
}

export interface Basket {
  id: number;
  session_id: number;
  status: "optimised" | "verified" | "pending_review" | "accepted" | "superseded";
  goal: Goal;
  total: number;
  budget: number | null;
  remaining: number | null;
  items: BasketItem[];
  summary: string | null;
  nutrition: Nutrition | null;
  requirements: Record<string, number> | null;
  metrics: Record<string, number> | null;
  verdict: string | null;
  excluded: { product: string; findings: { detail: string }[] }[];
  notifications: string[];
  strategy: string | null;
  cases: CaseBrief[];
}

export interface NegotiationOption {
  id: "increase_budget" | "reduce_days";
  label: string;
  detail: string;
  budget?: number;
  days?: number;
}

export interface Negotiation {
  message: string;
  options: NegotiationOption[];
  blocked_roles: string[];
  budget: number | null;
  days: number;
  person_meals: number;
  shortfall: number | null;
}

export interface MealSlot {
  slot: string;
  recipe: string | null;
  recipe_id?: string;
  servings?: number;
  minutes?: number;
  uses?: string[];
  optional?: string[];
  missing?: string[];
}

export interface MealPlan {
  id: number;
  basket_id: number;
  summary: string;
  days: { day: number; meals: MealSlot[] }[];
  requested: number;
  planned: number;
  missing: { day: number; slot: string; suggested_recipe: string; missing_tags: string[] }[];
  reused: string[];
  leftovers: { name: string; servings_left: number }[];
  expired_unused?: { name: string; servings_left: number }[];
  suggested_additions: { for: string; product: string }[];
  assumed_at_home: string[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  at: string;
}

export interface SessionState {
  session: { id: number; goal: Goal; status: string; created_at: string | null };
  intake: IntakeState | null;
  constraints: { version: number; payload: ConstraintDraft; origin: string } | null;
  basket: Basket | null;
  meal_plan: MealPlan | null;
  chat: ChatMessage[];
}

export interface Substitution {
  id: number;
  status: "pending" | "accepted" | "rejected" | "discarded";
  reason: string;
  trade_off: string;
  facts: { saving?: number; notes?: string[]; retailer?: string; unit_price?: number; unit_basis?: string };
  basket_item_id: number;
  original: { id: number; name: string };
  replacement: { id: number; name: string } | null;
  replacement_price: number | null;
}

export interface ComparisonOption {
  name: string;
  retailer_id: number | null;
  total: number;
  saving: number;
  saving_pct: number;
  complete: boolean;
  unpriced: string[];
  is_split: boolean;
}

export interface Comparison {
  basket_id: number;
  baseline: { id: number; name: string; total: number };
  options: ComparisonOption[];
  rows: {
    item_id: number;
    product: string;
    quantity: number;
    prices: Record<string, { pack_price: number; line: number; unit_price: number | null; unit_basis: string; on_special: boolean }>;
    cheapest_retailer_id: number | null;
  }[];
  retailers: { id: number; name: string; source: string }[];
  cheapest: ComparisonOption | null;
  insight: string | null;
  complete: boolean;
  refreshed_quotes: number;
}

export interface TimingAdvice {
  item_id: number;
  product: string;
  action: "wait" | "buy_now" | "none" | "skip";
  reason: string;
  wait_days?: number;
  pattern_day?: string;
  expected_saving?: number;
  confidence?: number;
}

/** The recorded inputs an explanation cites (KAN-27). Missing kinds are listed, never filled in. */
export interface ExplanationEvidence {
  constraints?: { version: number; budget: number | null; days: number | null; meals_per_day: number | null; household_size: number | null; restrictions: string[] } | null;
  prices?: { item: string; retailer: string; price: number; quote_id: number; captured_at: string; source: string | null }[] | null;
  unpriced_items?: string[];
  verdict?: { id: number; status: string; confidence: number; source: string } | null;
  tools?: { solver: Record<string, number> | null; solver_ms: number | null } | null;
  audit_trail?: { id: number; agent: string; action: string }[] | null;
  price?: { retailer: string; price: number; quote_id: number; captured_at: string } | null;
  compliance?: { status: string; confidence: number; findings: string[] } | null;
  missing: string[];
}

export interface Explanation {
  available: boolean;
  text: string;
  facts: Record<string, unknown> | null;
  evidence: ExplanationEvidence | null;
}

export interface HouseholdMember {
  id: number;
  name: string;
  age_group: string;
  restrictions: { id: number; restriction: string; kind: string; severity: string }[];
}

export interface Household {
  id: number;
  name: string;
  region: string;
  size: number;
  members: HouseholdMember[];
  preferences: { id: number; kind: string; value: string; source: string }[];
  mandatory_restrictions: Restriction[];
}

export interface EscalationCase extends CaseBrief {
  basket_id: number;
  basket_item_id: number | null;
  household_id: number;
  requirements: Restriction[];
  evidence: { confidence?: number; findings?: { kind: string; detail: string; restriction?: string; ingredient?: string }[]; household?: string };
  thread: { from: "reviewer" | "agent"; author: string; text: string; at: string }[];
  resolution_note: string | null;
  product_detail: { id: number; name: string; brand: string; ingredients: string[]; may_contain: string[]; data_complete: boolean; category: string };
  created_at: string | null;
  assigned_at: string | null;
  resolved_at: string | null;
  is_open: boolean;
}

export interface AuditEntry {
  id: number;
  timestamp: string | null;
  agent: string;
  action: string;
  decision: string;
  rationale: string;
  confidence: number | null;
  model_version: string;
  provider: string;
  session_id: number | null;
  basket_id: number | null;
  payload?: Record<string, unknown>;
}

export interface LlmStatus {
  provider: string;
  model: string;
  configured_provider: string;
  fallback_to_mock: boolean;
  config_error: string | null;
  last_error: string | null;
  last_error_at: string | null;
  calls: number;
  fallbacks: number;
}

export type WithTrace<T> = T & { trace: TraceStep[] };
