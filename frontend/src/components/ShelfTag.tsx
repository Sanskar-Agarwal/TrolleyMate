import { money } from "../lib/format";

/** Small deterministic tilt so a column of stickers looks hand-applied, not random per render. */
export const tiltFor = (seed: number) => `${((seed * 37) % 7) - 3}deg`;

/** Trolley Mate's price sticker, modelled on an Australian shelf ticket: big pack price, unit price beneath. */
export default function ShelfTag({
  price,
  unit,
  special = false,
  muted = false,
  seed = 1,
}: {
  price: number | null;
  unit?: string | null;
  special?: boolean;
  muted?: boolean;
  seed?: number;
}) {
  return (
    <span
      className={`shelf-tag${special ? " special" : ""}${muted ? " muted-tag" : ""}`}
      style={{ "--tilt": tiltFor(seed) } as React.CSSProperties}
    >
      <span className="price">{money(price)}</span>
      {unit && <span className="unit">{unit}</span>}
      {special && <span className="unit">ON SPECIAL</span>}
    </span>
  );
}
