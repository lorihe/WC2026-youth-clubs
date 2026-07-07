import csv
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LINEUPS_CSV = ROOT / "data" / "world_cup_match_lineups.csv"
OUTPUT_CSV = ROOT / "data" / "player_research_queue.csv"


def main() -> None:
    player_counts: dict[tuple[str, str], int] = defaultdict(int)
    player_urls: dict[tuple[str, str], str] = {}

    with LINEUPS_CSV.open("r", encoding="utf-8-sig", newline="") as infile:
        reader = csv.DictReader(infile)
        for row in reader:
            if not row.get("player_name") or not row.get("team_name"):
                continue
            key = (row["player_name"].strip(), row["team_name"].strip())
            player_counts[key] += 1
            if key not in player_urls:
                player_urls[key] = row.get("player_wikipedia_url", "").strip()

    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as outfile:
        fieldnames = ["player_name", "national_team", "player_wikipedia_url", "starting_xi_appearances"]
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        for (player_name, national_team), appearances in sorted(
            player_counts.items(),
            key=lambda item: (-item[1], item[0][1], item[0][0]),
        ):
            writer.writerow(
                {
                    "player_name": player_name,
                    "national_team": national_team,
                    "player_wikipedia_url": player_urls.get((player_name, national_team), ""),
                    "starting_xi_appearances": appearances,
                }
            )

    print(f"Wrote {len(player_counts)} player records to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
