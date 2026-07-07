import csv
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TRAINING_CSV = ROOT / "data" / "player_youth_training.csv"
OUTPUT_CSV = ROOT / "data" / "training_club_summary.csv"


def safe_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def main() -> None:
    club_years: dict[tuple[str, str], int] = defaultdict(int)
    club_players: dict[tuple[str, str], set[str]] = defaultdict(set)

    with TRAINING_CSV.open("r", encoding="utf-8-sig", newline="") as infile:
        reader = csv.DictReader(infile)
        for row in reader:
            team = (row.get("national_team") or "").strip()
            club = (row.get("club_name") or "").strip()
            player = (row.get("player_name") or "").strip()
            start_age = safe_int((row.get("start_age_est") or "").strip())
            end_age = safe_int((row.get("end_age_est") or "").strip())

            if not team or not club or not player:
                continue

            club_players[(team, club)].add(player)
            if start_age is not None and end_age is not None:
                years = max(0, end_age - start_age + 1)
                club_years[(team, club)] += years

    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as outfile:
        fieldnames = ["national_team", "club_name", "estimated_training_years", "players_trained"]
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        for team, club in sorted(
            club_players.keys(),
            key=lambda key: (-club_years.get(key, 0), -len(club_players[key]), key[0], key[1]),
        ):
            writer.writerow(
                {
                    "national_team": team,
                    "club_name": club,
                    "estimated_training_years": club_years.get((team, club), 0),
                    "players_trained": len(club_players[(team, club)]),
                }
            )

    print(f"Wrote {len(club_players)} summary rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
