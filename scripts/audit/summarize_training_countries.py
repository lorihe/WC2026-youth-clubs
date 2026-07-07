import csv
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TRAINING_CSV = ROOT / "data" / "player_youth_training.csv"
OUTPUT_CSV = ROOT / "data" / "training_country_summary.csv"


def safe_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def main() -> None:
    country_years: dict[tuple[str, str], int] = defaultdict(int)
    country_players: dict[tuple[str, str], set[str]] = defaultdict(set)

    with TRAINING_CSV.open("r", encoding="utf-8-sig", newline="") as infile:
        reader = csv.DictReader(infile)
        for row in reader:
            team = (row.get("national_team") or "").strip()
            country = (row.get("club_country") or "").strip()
            player = (row.get("player_name") or "").strip()
            start_age = safe_int((row.get("start_age_est") or "").strip())
            end_age = safe_int((row.get("end_age_est") or "").strip())

            if not team or not country or not player:
                continue

            country_players[(team, country)].add(player)
            if start_age is not None and end_age is not None:
                years = max(0, end_age - start_age + 1)
                country_years[(team, country)] += years

    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as outfile:
        fieldnames = ["national_team", "club_country", "estimated_training_years", "players_trained"]
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        for team, country in sorted(
            country_players.keys(),
            key=lambda key: (-country_years.get(key, 0), -len(country_players[key]), key[0], key[1]),
        ):
            writer.writerow(
                {
                    "national_team": team,
                    "club_country": country,
                    "estimated_training_years": country_years.get((team, country), 0),
                    "players_trained": len(country_players[(team, country)]),
                }
            )

    print(f"Wrote {len(country_players)} summary rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
