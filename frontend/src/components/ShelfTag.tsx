import { money } from "../lib/format";

/** Trolley Mate's price label, modelled on an Australian shelf ticket: big pack price, unit price beneath. */
export default function ShelfTag({
  price,
  unit,
  special = false,
  muted = false,
}: {
  price: number | null;
  unit?: string | null;
  special?: boolean;
  muted?: boolean;
}) {
  return (
    <span className={`shelf-tag${special ? " special" : ""}${muted ? " muted-tag" : ""}`}>
      <span className="price">{money(price)}</span>
      {unit && <span className="unit">{unit}</span>}
      {special && <span className="unit">SPECIAL</span>}
    </span>
  );
}
