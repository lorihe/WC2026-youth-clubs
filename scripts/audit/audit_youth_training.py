"""
Audit player_youth_training.csv for data quality issues.
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRAINING_CSV = ROOT / "data" / "player_youth_training.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            with path.open(encoding=encoding, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot decode {path}")


def norm(v: str | None) -> str:
    return (v or "").strip()


def safe_int(v: str) -> int | None:
    try:
        return int(v) if v.strip() else None
    except ValueError:
        return None


def normalize_club_name(name: str) -> str:
    """Lowercase, strip common suffixes for fuzzy comparison."""
    s = name.lower().strip()
    for suffix in (" fc", " f.c.", " f.c", " sc", " s.c.", " ac", " a.c.",
                   " united", " city", " town", " athletic", " athletics",
                   " cf", " fk", " bk", " if", " sk"):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
    s = re.sub(r"\s+", " ", s)
    return s


issues: list[dict] = []

def flag(category: str, player: str, team: str, detail: str, rows: list[dict] | None = None):
    issues.append({
        "category": category,
        "player": player,
        "national_team": team,
        "detail": detail,
        "rows": rows or [],
    })


def main() -> None:
    rows = read_csv(TRAINING_CSV)
    print(f"Loaded {len(rows)} rows.\n")

    # Group by player
    by_player: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        key = (norm(row["player_name"]), norm(row["national_team"]))
        by_player[key].append(row)

    for (player, team), player_rows in sorted(by_player.items()):

        # ── 1. Exact duplicate rows (same club + same year range) ──────────
        seen_combos: dict[tuple, list] = defaultdict(list)
        for row in player_rows:
            combo = (
                norm(row["club_name"]).lower(),
                norm(row["start_year_est"]),
                norm(row["end_year_est"]),
                norm(row["start_age_est"]),
                norm(row["end_age_est"]),
            )
            seen_combos[combo].append(row)
        for combo, dup_rows in seen_combos.items():
            if len(dup_rows) > 1:
                flag(
                    "DUPLICATE_ROW",
                    player, team,
                    f"Club '{dup_rows[0]['club_name']}' years {combo[1]}–{combo[2]} "
                    f"appears {len(dup_rows)} times",
                    dup_rows,
                )

        # ── 2. Same club listed twice under near-identical names ───────────
        norm_to_names: dict[str, list[str]] = defaultdict(list)
        for row in player_rows:
            n = normalize_club_name(norm(row["club_name"]))
            if n:
                norm_to_names[n].append(norm(row["club_name"]))
        for norm_name, variants in norm_to_names.items():
            unique_variants = sorted(set(variants))
            if len(unique_variants) > 1:
                flag(
                    "CLUB_NAME_VARIANT",
                    player, team,
                    f"Same club appears as: {unique_variants}",
                )

        # ── 3. Overlapping age/year spans across different clubs ───────────
        dated = [
            r for r in player_rows
            if norm(r["start_year_est"]) and norm(r["end_year_est"])
        ]
        dated.sort(key=lambda r: (safe_int(r["start_year_est"]) or 0,
                                  safe_int(r["end_year_est"]) or 0))

        for i in range(len(dated) - 1):
            r1 = dated[i]
            r2 = dated[i + 1]
            s1, e1 = safe_int(r1["start_year_est"]), safe_int(r1["end_year_est"])
            s2, e2 = safe_int(r2["start_year_est"]), safe_int(r2["end_year_est"])
            if s1 is None or e1 is None or s2 is None or e2 is None:
                continue
            if norm(r1["club_name"]).lower() == norm(r2["club_name"]).lower():
                continue  # same club consecutive — handled elsewhere
            overlap_start = max(s1, s2)
            overlap_end = min(e1, e2)
            if overlap_start < overlap_end:  # more than a single boundary year
                flag(
                    "YEAR_OVERLAP",
                    player, team,
                    f"'{r1['club_name']}' {s1}–{e1} overlaps "
                    f"'{r2['club_name']}' {s2}–{e2} "
                    f"(overlap: {overlap_start}–{overlap_end})",
                )

        # ── 4. Year/age mismatch (age doesn't match year given birth_year) ──
        for row in player_rows:
            sy = safe_int(row["start_year_est"])
            ey = safe_int(row["end_year_est"])
            sa = safe_int(row["start_age_est"])
            ea = safe_int(row["end_age_est"])
            if None in (sy, ey, sa, ea):
                continue
            if ey < sy:
                flag(
                    "YEAR_ORDER",
                    player, team,
                    f"'{row['club_name']}': end_year ({ey}) < start_year ({sy})",
                    [row],
                )
            if ea < sa:
                flag(
                    "AGE_ORDER",
                    player, team,
                    f"'{row['club_name']}': end_age ({ea}) < start_age ({sa})",
                    [row],
                )
            # Check age-year consistency using each other
            if sy and sa and ey and ea:
                implied_birth_from_start = sy - sa
                implied_birth_from_end = ey - ea
                if abs(implied_birth_from_start - implied_birth_from_end) > 1:
                    flag(
                        "AGE_YEAR_MISMATCH",
                        player, team,
                        f"'{row['club_name']}': start {sy} age {sa} implies birth ~{implied_birth_from_start}, "
                        f"but end {ey} age {ea} implies birth ~{implied_birth_from_end}",
                        [row],
                    )

        # ── 5. Gap between consecutive club spells (>2 years unaccounted) ──
        if len(dated) >= 2:
            for i in range(len(dated) - 1):
                e1 = safe_int(dated[i]["end_year_est"])
                s2 = safe_int(dated[i + 1]["start_year_est"])
                if e1 is None or s2 is None:
                    continue
                gap = s2 - e1
                if gap > 2:
                    flag(
                        "YEAR_GAP",
                        player, team,
                        f"Gap of {gap} years between "
                        f"'{dated[i]['club_name']}' (ends {e1}) and "
                        f"'{dated[i+1]['club_name']}' (starts {s2})",
                    )

        # ── 6. Ages outside 5–16 window ────────────────────────────────────
        for row in player_rows:
            sa = safe_int(row["start_age_est"])
            ea = safe_int(row["end_age_est"])
            if sa is not None and (sa < 5 or sa > 16):
                flag("AGE_OUT_OF_WINDOW", player, team,
                     f"'{row['club_name']}': start_age {sa} outside 5–16",
                     [row])
            if ea is not None and (ea < 5 or ea > 16):
                flag("AGE_OUT_OF_WINDOW", player, team,
                     f"'{row['club_name']}': end_age {ea} outside 5–16",
                     [row])

        # ── 7. Conflicting club_country for same club_name ─────────────────
        club_countries: dict[str, set[str]] = defaultdict(set)
        for row in player_rows:
            cn = norm(row["club_name"]).lower()
            cc = norm(row["club_country"])
            if cn and cc:
                club_countries[cn].add(cc)
        for club, countries in club_countries.items():
            if len(countries) > 1:
                flag(
                    "CONFLICTING_CLUB_COUNTRY",
                    player, team,
                    f"'{club}' has multiple countries: {sorted(countries)}",
                )

        # ── 8. Same Wikipedia URL for two different-named clubs ────────────
        url_to_clubs: dict[str, set[str]] = defaultdict(set)
        for row in player_rows:
            url = norm(row["club_wikipedia_url"])
            cname = norm(row["club_name"]).lower()
            if url:
                url_to_clubs[url].add(cname)
        for url, clubs in url_to_clubs.items():
            if len(clubs) > 1:
                flag(
                    "SHARED_WIKIPEDIA_URL",
                    player, team,
                    f"URL '{url}' shared by clubs: {sorted(clubs)}",
                )

    # ── Print results ──────────────────────────────────────────────────────
    by_category: dict[str, list] = defaultdict(list)
    for issue in issues:
        by_category[issue["category"]].append(issue)

    category_labels = {
        "DUPLICATE_ROW":           "1. Duplicate rows (same club + years)",
        "CLUB_NAME_VARIANT":       "2. Same club under different name variants",
        "YEAR_OVERLAP":            "3. Overlapping year spans across different clubs",
        "YEAR_ORDER":              "4. End year before start year",
        "AGE_ORDER":               "5. End age before start age",
        "AGE_YEAR_MISMATCH":       "6. Age–year inconsistency",
        "YEAR_GAP":                "7. Large gap (>2 yrs) between consecutive clubs",
        "AGE_OUT_OF_WINDOW":       "8. Ages outside 5–16 window",
        "CONFLICTING_CLUB_COUNTRY":"9. Conflicting club country for same club",
        "SHARED_WIKIPEDIA_URL":    "10. Same Wikipedia URL for different club names",
    }

    total = 0
    for cat, label in category_labels.items():
        cat_issues = by_category.get(cat, [])
        total += len(cat_issues)
        if not cat_issues:
            print(f"{label}: no issues found")
            continue
        print(f"\n{'─'*70}")
        print(f"{label}: {len(cat_issues)} issue(s)")
        print(f"{'─'*70}")
        for iss in cat_issues:
            print(f"  [{iss['national_team']}] {iss['player']}  →  {iss['detail']}")

    print(f"\n{'═'*70}")
    print(f"TOTAL ISSUES FOUND: {total}")


if __name__ == "__main__":
    main()
