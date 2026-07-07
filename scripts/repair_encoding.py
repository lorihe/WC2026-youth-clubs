"""Repair lossy-encoding corruption in player_youth_training.csv.

The working CSV was saved in a Western codepage that destroyed Latin
Extended-A characters (š, ž, č, ć, ...): some became a literal '?' and others
were transliterated to their base letter. This restores the correct spellings
and rewrites the file as clean UTF-8.

  * Player names -> world_cup_match_lineups.csv (clean UTF-8, authoritative),
                    matched by an ASCII-folded wildcard where '?' is any char.
  * Club names   -> a small fixed correction table (clubs are not in the
                    lineups file and there is no other clean source).

Run once; afterwards the file is clean UTF-8 and name matching works normally.
"""
import csv
import io
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TRAINING = DATA / "player_youth_training.csv"
LINEUPS = DATA / "world_cup_match_lineups.csv"

# Corrupted club name -> correct spelling. Derived from the committed UTF-16
# version; the two "(loan)" entries had an unrecoverable stray leading char
# (their Wikipedia URLs confirm the club), so the prefix is dropped.
CLUB_FIXES = {
    "?eljeznicar": "Željezničar",
    "GO?K Ka?tel Gomilica": "GOŠK Kaštel Gomilica",
    "Radnik Had?ici": "Radnik Hadžići",
    "SK Tou?im": "SK Toužim",
    "Tre?njevka": "Trešnjevka",
    "Viktoria ?i?kov": "Viktoria Žižkov",
    "? Eibar (loan)": "Eibar (loan)",
    "? Sevilla (loan)": "Sevilla (loan)",
}


def afold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()


def wildcard(name: str) -> re.Pattern:
    """Regex from an ASCII-folded corrupted name; '?' matches exactly one char."""
    parts = ["." if ch == "?" else re.escape(ch) for ch in afold(name)]
    return re.compile("^" + "".join(parts) + "$")


def main() -> None:
    # WORK decodes correctly as cp1252 for every byte except the lost '?' chars.
    work_rows = list(csv.DictReader(io.StringIO(TRAINING.read_bytes().decode("cp1252"))))
    fieldnames = list(work_rows[0].keys())

    lineups = list(csv.DictReader(io.StringIO(LINEUPS.read_bytes().decode("utf-8-sig"))))
    lineup_by_team: dict[str, set] = {}
    for r in lineups:
        lineup_by_team.setdefault(r["team_name"], set()).add(r["player_name"])

    # Build player-name repair map from clean lineups names.
    player_map: dict[tuple, str] = {}
    unresolved_names = []
    for name, team in {(r["player_name"], r["national_team"]) for r in work_rows if "?" in r["player_name"]}:
        pat = wildcard(name)
        cands = [c for c in lineup_by_team.get(team, set()) if pat.match(afold(c))]
        if len(cands) == 1:
            player_map[(name, team)] = cands[0]
        else:
            unresolved_names.append((name, team, cands))

    # Apply repairs.
    p_fixed = c_fixed = 0
    for r in work_rows:
        pk = (r["player_name"], r["national_team"])
        if pk in player_map:
            r["player_name"] = player_map[pk]
            p_fixed += 1
        if r["club_name"] in CLUB_FIXES:
            r["club_name"] = CLUB_FIXES[r["club_name"]]
            c_fixed += 1

    remaining = sum(1 for r in work_rows if "?" in r["player_name"] or "?" in r["club_name"])

    # Write clean UTF-8 (no BOM), CRLF to match the original CSV line endings.
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\r\n")
    w.writeheader()
    w.writerows(work_rows)
    TRAINING.write_bytes(buf.getvalue().encode("utf-8"))

    print(f"Repaired {p_fixed} player-name rows ({len(player_map)} distinct names)")
    print(f"Repaired {c_fixed} club-name rows ({len(CLUB_FIXES)} distinct clubs)")
    if unresolved_names:
        print(f"WARNING: {len(unresolved_names)} corrupted player names could not be resolved:")
        for name, team, cands in unresolved_names:
            print(f"   [{team}] {name!r} candidates={cands}")
    print(f"Rows still containing '?': {remaining}")
    print(f"Wrote clean UTF-8: {TRAINING}")


if __name__ == "__main__":
    main()
