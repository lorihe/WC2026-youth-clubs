import csv
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            with path.open(encoding=encoding, newline="") as infile:
                return list(csv.DictReader(infile))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot decode {path}")


def norm(value: str | None) -> str:
    return (value or "").strip()


def row_key(row: dict[str, str]) -> tuple[str, ...]:
    return (
        norm(row.get("player_name")),
        norm(row.get("national_team")),
        norm(row.get("club_name")),
        norm(row.get("club_wikipedia_url")),
        norm(row.get("start_age_est")),
        norm(row.get("end_age_est")),
        norm(row.get("start_year_est")),
        norm(row.get("end_year_est")),
    )


def main() -> None:
    verified_path = Path(r"C:\Users\lorih\Desktop\player_youth_training_club_country_verified.csv")
    current_path = Path(r"d:\Sports\youth club\data\player_youth_training.csv")

    verified = read_csv(verified_path)
    current = read_csv(current_path)

    v_by_key = {row_key(row): row for row in verified}
    c_by_key = {row_key(row): row for row in current}

    common = set(v_by_key) & set(c_by_key)
    only_verified = set(v_by_key) - set(c_by_key)
    only_current = set(c_by_key) - set(v_by_key)

    print(f"Verified rows: {len(verified)}")
    print(f"Current rows: {len(current)}")
    print(f"Common rows: {len(common)}")
    print(f"Only in verified file: {len(only_verified)}")
    print(f"Only in current file: {len(only_current)}")
    print()

    same = 0
    both_empty = 0
    diffs: list[dict[str, str]] = []

    for key in common:
        verified_country = norm(v_by_key[key].get("verified_club_country"))
        current_country = norm(c_by_key[key].get("club_country"))
        if verified_country == current_country:
            same += 1
            if not verified_country:
                both_empty += 1
            continue

        diffs.append(
            {
                "player_name": key[0],
                "national_team": key[1],
                "club_name": key[2],
                "verified_club_country": verified_country,
                "club_country": current_country,
                "original_club_country": norm(v_by_key[key].get("original_club_country")),
                "status": norm(v_by_key[key].get("country_verification_status")),
                "note": norm(v_by_key[key].get("country_verification_note")),
            }
        )

    print("=== COMPARISON ON MATCHING ROWS ===")
    print(f"Same value (including both empty): {same}")
    print(f"Both empty: {both_empty}")
    print(f"Different values: {len(diffs)}")
    print(f"Verified filled, current empty: {sum(1 for d in diffs if d['verified_club_country'] and not d['club_country'])}")
    print(f"Current filled, verified empty: {sum(1 for d in diffs if d['club_country'] and not d['verified_club_country'])}")
    print(f"Both filled but different: {sum(1 for d in diffs if d['verified_club_country'] and d['club_country'] and d['verified_club_country'] != d['club_country'])}")

    if diffs:
        print()
        print("=== ALL DIFFERENCES ===")
        for item in sorted(diffs, key=lambda row: (row["national_team"], row["player_name"], row["club_name"])):
            print(
                f"{item['player_name']} | {item['club_name']} | "
                f"verified={item['verified_club_country']!r} | current={item['club_country']!r} | "
                f"original={item['original_club_country']!r} | status={item['status']}"
            )


if __name__ == "__main__":
    main()
