# Catalogue Data Provenance

**Schema version:** 1.1.0  
**Generated:** 2026-10-27  
**Owner:** Chen-Ju Lin (KAN-13)  
**Agreed with:** Reyon (Retailer integration, KAN-14)

Counts and behaviour verified against the checked-in seed and source on 2026-10-29.
The generated date above is the value stored in `catalogue.json`.

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

All data in `catalogue.json` is **synthetic** — it was authored for the demo and does not come from any real retailer system. Within the seeded database, rows are tagged by `price_quotes.source_type`; these tags describe simulated quote roles, not evidence of a real retailer source:

| `source_type` | Meaning | How generated |
|---|---|---|
| `synthetic` | Seed-time current price for a catalogue-adapter retailer | `base_price` × category/default retailer multiplier × deterministic price variation (up to ±6%), rounded to cents |
| `recorded` | Historical snapshot (past 8 weeks) | Generated in `_seed_prices()` loop, `week` = 1…8 |
| `live` | Seeded current quote for a partner-API retailer | Computed at seed time for FreshCo; simulates a live-feed quote but is still synthetic data |

At runtime, the partner adapter uses a simulated feed when `PARTNER_API_URL` is unset;
those refreshed quotes are tagged `synthetic`. A successful configured partner response
is tagged `live`, while partner errors can fall back to simulated quotes. The seed's
`live` tag alone must not be presented as proof of a real integration.

---

## Product catalogue

- **109 products** across 7 categories: `protein` (21), `carb` (16), `veg` (19), `dairy` (14), `fruit` (12), `pantry` (14), `snack` (13).
- All products contain fields for SKU, name, brand, category, pack size, unit (g / ml / each), servings, nutrition (per pack), ingredients, tags, perishable flag, shelf-life, prep time and substitution group. Presence does not imply completeness: the fixtures below include null nutrition values and empty ingredient lists.
- Pricing: `base_price` in AUD; each retailer applies category/default multipliers (see `retailers[].multipliers`) and deterministic price variation. Availability exclusions are retained.
- Specials: some products carry a `specials` map keyed by retailer name, each with a discounted `price` and a `weekdays` list (Monday = 0). Historical seed prices include these special periods and the return to regular pricing.

### Nutrition fields (per pack)

| Field | Unit | Notes |
|---|---|---|
| `kcal` | kcal | Total energy |
| `protein_g` | g | |
| `carbs_g` | g | Total carbohydrates |
| `fat_g` | g | Total fat |
| `fibre_g` | g | |
| `veg_serves` | count | Synthetic vegetable-serve estimate used by the demo's nutrition constraints |

---

## Edge cases and test fixtures

The catalogue includes malformed, incomplete, unavailable and stale cases for the demo
(KAN-13 acceptance criterion: "provide malformed and stale cases"):

| SKU | Type | Description |
|---|---|---|
| `PRO-MAL-BAR` | **Malformed** | Nutrition panel is `null` throughout — simulates a retailer feed where the nutrition block could not be parsed. `data_complete: false`. No ingredients list. |
| `PRO-DIS-STEAK` | **Discontinued / fully unavailable** | Listed in catalogue but marked `unavailable_at` all four retailers — simulates a delisted item still present in a cached feed. Generates no `PriceQuote` rows. |
| `PRO-SCH-1K` | **Incomplete** | `data_complete: false`, empty ingredients — synthetic example of a retailer feed that omits ingredient lists. |
| `FreshCo` quotes | **Stale at seed time** | Current FreshCo quotes are seeded with capture times 30 h earlier and `status = stale`, exercising the stale-refresh flow. Refreshing replaces these with newly captured quotes. |
| `PRO-LMB-500` | **Retailer exclusion** | Unavailable at ValueMart only. |
| `CRB-GFP-500` | **Retailer exclusion** | Unavailable at GreenGrocer Express only. |
| `FRU-BAN-1K` | **Retailer exclusion** | Unavailable at Harvest Market only. |

---

## Ingredients and allergen tags

The seed contains **102 ingredients**, including four composite ingredients and seven
marked `ambiguous: true`. Ingredient tags mix allergen, dietary-restriction and food-group
labels; they are a prototype vocabulary rather than an exhaustive regulatory allergen list:

`animal_rennet`, `egg`, `fish`, `fruit`, `gelatine`, `gluten`, `honey`, `lactose`, `meat`, `milk`, `peanuts`, `pork`, `sesame`, `shellfish`, `soy`, `tree_nuts`, `vegetable`, `wheat`

Composite ingredients (e.g. `basil pesto`) are expanded recursively so allergen checks cascade (requirement 1.2.10).  
Ambiguous ingredients (e.g. `spices`, `natural flavours`) are assessed against applicable
restrictions using the configured model or offline mock and bundled guidance. They do
not invariably produce `uncertain`: a sufficiently confident `none` risk judgement can
leave a product `compliant`, while possible risk, low confidence or assessment failure
leaves it uncertain and likely risk produces a violation. A failed-provider fallback
cannot clear an ambiguous ingredient as risk-free. These labels describe prototype
screening, not verified product safety.

---

## Update process

1. Edit `catalogue.json` directly.
2. Update `generated_at` and the counts/fixtures in this document; bump `schema_version`
   (semver) when the data contract changes and keep `product_schema.json` aligned.
3. Validate the catalogue with the focused catalogue tests. To reload a **disposable demo
   database**, run `python -m app.seed --reset` from `backend/`. This drops and recreates
   application tables, including users and sessions. Normal startup only seeds when no
   user exists and does not merge catalogue edits into an existing database.
4. Coordinate schema-breaking changes with Reyon before merging to `main`; plan a
   migration separately if existing application data must be retained.
