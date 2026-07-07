"""Merge verified_club_country into player_youth_training.csv."""
import csv
from pathlib import Path

VERIFIED = Path(r"C:\Users\lorih\Desktop\player_youth_training_club_country_verified.csv")
TRAINING = Path(r"D:\Sports\youth club\data\player_youth_training.csv")


def read_csv(path: Path) -> list[dict[str, str]]:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot decode {path}")


def row_key(row: dict) -> tuple:
    def n(v): return (v or "").strip()
    return (
        n(row.get("player_name")), n(row.get("national_team")), n(row.get("club_name")),
        n(row.get("club_wikipedia_url")), n(row.get("start_age_est")), n(row.get("end_age_est")),
        n(row.get("start_year_est")), n(row.get("end_year_est")),
    )


def main() -> None:
    verified = read_csv(VERIFIED)
    v_by_key = {row_key(r): (r.get("verified_club_country") or "").strip() for r in verified}

    training = read_csv(TRAINING)
    fieldnames = list(training[0].keys()) if training else []

    filled = corrected = 0
    for row in training:
        v_country = v_by_key.get(row_key(row), "")
        cur_country = (row.get("club_country") or "").strip()
        if v_country and v_country != cur_country:
            if cur_country:
                corrected += 1
                print(f"  CORRECTED [{row['national_team']}] {row['player_name']} | "
                      f"{row['club_name']}: '{cur_country}' → '{v_country}'")
            else:
                filled += 1
            row["club_country"] = v_country

    with TRAINING.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(training)

    with_country = sum(1 for r in training if (r.get("club_country") or "").strip())
    print(f"\nRows updated: {filled + corrected}  (empty filled: {filled}, corrected: {corrected})")
    print(f"Total rows with club_country: {with_country} / {len(training)}")


if __name__ == "__main__":
    main()
