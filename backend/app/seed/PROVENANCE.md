# Catalogue Data Provenance

**Schema version:** 1.1.0  
**Generated:** 2026-10-27  
**Owner:** Chen-Ju Lin (KAN-13)  
**Agreed with:** Reyon (Retailer integration, KAN-14)

---

## Retailers

| Name | Region | Source adapter | Role in demo |
|---|---|---|---|
| GreenGrocer Express | Sydney Metro | `catalogue` | Premium grocer; higher default markup; discount on fruit/veg |
| ValueMart | Sydney Metro | `catalogue` | Budget chain; discount on pantry/carb; markup on veg |
| FreshCo | Sydney Metro | `partner_api` | Simulates live partner API; quotes seeded 30 h old to demonstrate stale-refresh |
| Harvest Market | Sydney Metro | `catalogue` | Discount grocer; cheaper protein/dairy, dearer fruit/snacks; 21 own specials; bananas out of stock |

The demo uses **four** retailers, which satisfies the "bounded multi-retailer" requirement of 1.2.7 and extends the minimum two-retailer contract agreed with Reyon. The price comparison prices every basket item at all four and lists the cheapest source per item (`split_plan`).

---

## Data classification

All data in `catalogue.json` is **synthetic** — it was authored for the demo and does not come from any real retailer system.  Within the seeded database, rows are tagged by `price_quotes.source_type`:

| `source_type` | Meaning | How generated |
|---|---|---|
| `synthetic` | Seed-time price for a catalogue-adapter retailer | Computed once at `seed_all()` from `base_price` × retailer multiplier |
| `recorded` | Historical snapshot (past 8 weeks) | Generated in `_seed_prices()` loop, `week` = 1…8 |
| `live` | Quote from a partner-API retailer | Computed at seed time for FreshCo; marks the quote as if it came from a live feed |

---

## Product catalogue

- **107 products** (including the two fixtures below) across 7 categories: `protein`, `carb`, `veg`, `dairy`, `fruit`, `pantry`, `snack`.
- All products have: SKU, name, brand, category, pack size, unit (g / ml / each), servings, nutrition (per pack), ingredients, tags, perishable flag, shelf-life, prep time, substitution group.
- Pricing: `base_price` in AUD; each retailer applies category multipliers (see `retailers[].multipliers`).
- Specials: some products carry a `special` block with a weekday and discounted price.

### Nutrition fields (per pack)

| Field | Unit | Notes |
|---|---|---|
| `kcal` | kcal | Total energy |
| `protein_g` | g | |
| `carbs_g` | g | Total carbohydrates |
| `fat_g` | g | Total fat |
| `fibre_g` | g | |
| `veg_serves` | count | Australian Guide to Healthy Eating serves |

---

## Edge cases and test fixtures

Two products are included specifically to exercise error paths (KAN-13 acceptance criterion: "provide malformed and stale cases"):

| SKU | Type | Description |
|---|---|---|
| `PRO-MAL-BAR` | **Malformed** | Nutrition panel is `null` throughout — simulates a retailer feed where the nutrition block could not be parsed. `data_complete: false`. No ingredients list. |
| `PRO-DIS-STEAK` | **Discontinued / fully unavailable** | Listed in catalogue but marked `unavailable_at` all four retailers — simulates a delisted item still present in a cached feed. Generates no `PriceQuote` rows. |
| `PRO-SCH-1K` | **Incomplete** | `data_complete: false`, empty ingredients — real partial-data example from a retailer that does not publish ingredient lists. |
| `FreshCo` quotes | **Stale** | All current FreshCo quotes are captured 30 h ago and have `status = stale` — drives the stale-refresh flow (UC-03). |
| `PRO-LMB-500` | **Retailer exclusion** | Unavailable at ValueMart only. |
| `CRB-GFP-500` | **Retailer exclusion** | Unavailable at GreenGrocer Express only. |
| `FRU-BAN-1K` | **Retailer exclusion** | Unavailable at Harvest Market only. |

---

## Ingredients and allergen tags

Ingredients carry restriction tags aligned with the eight major Australian allergens plus common intolerances:

`milk`, `lactose`, `wheat`, `gluten`, `egg`, `soy`, `tree_nuts`, `peanuts`, `fish`, `shellfish`, `sesame`, `honey`, `pork`

Composite ingredients (e.g. `basil pesto`) are expanded recursively so allergen checks cascade (requirement 1.2.10).  
Ambiguous ingredients (e.g. `spices`, `natural flavours`) are flagged with `ambiguous: true` and surface as `uncertain` compliance in the basket.

---

## Update process

1. Edit `catalogue.json` directly.
2. Bump `schema_version` (semver) and update `generated_at`.
3. Run `python -m app.seed --reset` to reload the database.
4. Coordinate schema-breaking changes with Reyon before merging to `main`.
