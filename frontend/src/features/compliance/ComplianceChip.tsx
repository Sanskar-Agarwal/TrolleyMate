import type { BasketItem } from "../../api/types";

/** Per-item safety status from the AI Nutrition & Compliance agent (UC-06). */
export default function ComplianceChip({ status, withheld }: { status: BasketItem["compliance"]; withheld: boolean }) {
  if (withheld) return <span className="chip chip-amber">Held for review</span>;
  if (status === "compliant") return <span className="chip chip-produce">Safe for household</span>;
  if (status === "violation") return <span className="chip chip-beet">Not safe</span>;
  if (status === "uncertain") return <span className="chip chip-amber">Uncertain</span>;
  return <span className="chip">Not checked</span>;
}
