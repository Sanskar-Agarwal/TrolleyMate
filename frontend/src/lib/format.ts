export const money = (n: number | null | undefined) => (n == null ? "N/A" : `$${n.toFixed(2)}`);

export const pct = (n: number) => `${n.toFixed(0)}%`;

export const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const sentence = (s: string) => {
  const t = s.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
};

export const time = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString("en-AU", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "";

export const dateTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString("en-AU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";

export const GOAL_LABEL: Record<string, string> = {
  lowest_cost: "Lowest cost",
  best_nutrition: "Best nutrition",
  least_waste: "Least waste",
  fastest_cook: "Quickest to cook",
  balanced: "Balanced",
};

export const NUTRIENT_LABEL: Record<string, string> = {
  kcal: "Energy",
  protein_g: "Protein",
  veg_serves: "Veg serves",
  staple_serves: "Staples",
  fibre_g: "Fibre",
};

export const nutrientValue = (key: string, v: number) =>
  key === "kcal" ? `${Math.round(v).toLocaleString()} kcal` : key.endsWith("_g") ? `${Math.round(v)} g` : `${Math.round(v)}`;
