# WC 2026 Youth Training Analysis

Where did FIFA World Cup 2026 starting-lineup players train between ages 5 and 16?
This project collects each starter's youth clubs and summarizes the results by
club and country.

## Data

| File | What it is |
|---|---|
| `data/world_cup_match_lineups.csv` | Starting XIs from completed matches |
| `data/player_youth_training.csv` | Each starter's youth clubs (ages 5–16) |
| `data/training_club_summary.csv` | Training years summarized by club |
| `data/training_country_summary.csv` | Training years summarized by country |
| `data/qualified_teams.csv` | The 48 qualified teams |
| `WC2026_Youth_Training_Report.pdf` | Generated summary report |

## Scripts

Grouped by stage:

- `scripts/scrape/` — collect starting XIs and a first pass of youth clubs from Wikipedia
- `scripts/enrich/` — backfill club countries and merge researched data
- `scripts/audit/` — build the summaries and check the data for gaps
- `scripts/generate_pdf_report.py` — build the PDF report

To regenerate the report:

```bash
python scripts/generate_pdf_report.py
```

## Coverage

- 75 completed matches
- 1,650 starting-XI rows
- 754 unique starters
- 1,429 youth-club rows (all with a club country)

## Note

The World Cup was still in progress as of 2026-07-05, so the dataset is updated
as more matches are played. CSVs are UTF-8 — if you edit them in Excel, save as
"CSV UTF-8" to preserve accented names.
