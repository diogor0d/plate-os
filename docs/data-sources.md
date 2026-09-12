# Food Data Sources

PlateOS ships compact, read-only snapshots of official generic-food datasets.
Search results are ephemeral candidates: retrieval never writes a product or a
meal, and the user must review and explicitly accept a candidate. PlateOS stores
the upstream record identifier and dataset version with accepted products.

## Anses Ciqual

- Snapshot: `backend/app/data/ciqual-2025.json`
- Release: Ciqual 2025, version `2025-11-19`
- Attribution: Anses. 2025. Table de composition nutritionnelle des aliments
  Ciqual 2025.
- Source: https://doi.org/10.57745/RDMHWY
- License: Licence Ouverte / Etalab 2.0
- License text: https://www.etalab.gouv.fr/licence-ouverte-open-licence/
- Included: 2,855 of 3,484 foods with exact numeric values for all five PlateOS
  nutrients.

The generator joins foods and composition records by `alim_code`. It uses the
EU-label energy/protein pair (`const_code` 328 and 25003), carbohydrates 31000,
fat 40000, and fiber 34100. Values marked as missing, traces, inequalities, or
otherwise non-numeric are not converted to zero.

Official inputs:

- Foods XML: https://entrepot.recherche.data.gouv.fr/api/access/datafile/666252
- Composition XML: https://entrepot.recherche.data.gouv.fr/api/access/datafile/666249

## Swedish Food Agency

- Snapshot: `backend/app/data/swedish-food-agency-2026-07-01.json`
- Release: `Livsmedelsverkets Livsmedelsdatabas version 2026-07-01`
- Source: https://soknaringsinnehall.livsmedelsverket.se/
- API documentation: https://dataportal.livsmedelsverket.se/livsmedel/swagger/index.html
- License: Creative Commons Attribution 4.0 International
- License text: https://creativecommons.org/licenses/by/4.0/
- Included: 2,605 of 2,606 foods with exact numeric values inside PlateOS's
  per-100-g limits.

The official full-database workbook supplies Swedish names and nutrients. The
official API's `sprak=2` food list supplies English names joined by `nummer`.
One record is excluded because its reported fat value exceeds PlateOS's physical
limit of 100 g/100 g; the value is not altered.

Official inputs:

- Full workbook: `POST https://soknaringsinnehall.livsmedelsverket.se/Spara/HamtaHelaDatabasen`
- English names: `GET https://dataportal.livsmedelsverket.se/livsmedel/api/v1/livsmedel?offset=0&limit=10000&sprak=2`

## Regeneration

Download the four official inputs, then run:

```text
python scripts/generate_food_catalogs.py --ciqual-foods <foods.xml> --ciqual-composition <composition.xml> --swedish-xlsx <database.xlsx> --swedish-english-names <foods-en.json> --output-dir backend/app/data
```

What it does: rebuilds deterministic compact snapshots and embeds SHA-256
checksums of every official input for review. The generator refuses inputs that
do not match its pinned hashes. Review release metadata, record counts, nutrient
identifiers, licensing, and the generated diff, then intentionally update the
pinned hashes and filenames when adopting a new release.
