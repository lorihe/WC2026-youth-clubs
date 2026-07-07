# WC 2026 Youth Training Analysis

This workspace is set up to collect and analyze where FIFA World Cup 2026 starting-lineup players were trained between ages 5 and 16.

## What this project is tracking

- All 48 qualified teams
- Starting XIs from completed World Cup matches
- Every identified youth club or academy attended by each starter between ages 5 and 16
- A country-level summary of where those training years happened

## Current status

- `data/qualified_teams.csv` contains the 48 qualified teams, their confederations, and FIFA codes.
- `data/world_cup_match_lineups.csv` is the match-level table for starting XIs.
- `data/player_youth_training.csv` is the player-level youth-training table.
- `data/training_club_summary.csv` summarizes estimated training years by national team and youth club.
- `data/training_country_summary.csv` summarizes estimated training years and player counts by national team and training country.
- `docs/collection_method.md` explains the source hierarchy, age-banding rules, and quality checks.
- `WC2026_Youth_Training_Report.pdf` is the generated summary report.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/scrape_world_cup_lineups.py` | Scrapes starting XIs from completed World Cup matches |
| `scripts/prefill_youth_from_wikipedia.py` | First-pass youth-club prefill from Wikipedia |
| `scripts/backfill_club_countries.py` | Backfills training country from club-level lookup |
| `scripts/build_research_queue.py` | Builds the queue of players still needing manual research |
| `scripts/enrich_youth_research.py` | Merges manually researched youth data back into the main table |
| `scripts/merge_verified_countries.py` | Merges verified country data into the training table |
| `scripts/compare_club_country.py` | Compares club-level vs. country-level training coverage |
| `scripts/summarize_training_clubs.py` | Generates `training_club_summary.csv` |
| `scripts/summarize_training_countries.py` | Generates `training_country_summary.csv` |
| `scripts/audit_youth_training.py` | Audits the training table for gaps and anomalies |
| `scripts/generate_pdf_report.py` | Generates `WC2026_Youth_Training_Report.pdf` |

## Important limitation

As of `2026-07-05`, the FIFA World Cup is still in progress, so an "all matches" starting-XI dataset cannot yet be complete. The structure here is designed so the dataset can be updated as additional matches are played.

## Recommended workflow

1. Fill `data/world_cup_match_lineups.csv` from completed World Cup matches.
2. Deduplicate players across matches.
3. Use player Wikipedia pages for a first-pass youth-club prefill where available.
4. Research remaining players and missing details from Transfermarkt and official bios.
5. Record every known club spell in `data/player_youth_training.csv`.
6. Build summary outputs by team, club, and country.

## Current data coverage

- `75` completed World Cup matches
- `1,650` starting-XI rows
- `754` unique starters
- `1,385` youth-club rows
- `1,385` youth-club rows with a backfilled club country (100%)
- `52` remaining unresolved players with no training data
