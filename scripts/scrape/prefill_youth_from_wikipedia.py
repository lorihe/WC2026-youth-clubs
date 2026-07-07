import csv
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag


ROOT = Path(__file__).resolve().parents[2]
LINEUPS_CSV = ROOT / "data" / "world_cup_match_lineups.csv"
OUTPUT_CSV = ROOT / "data" / "player_youth_training.csv"
MISSING_CSV = ROOT / "data" / "player_youth_training_missing.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CursorResearchBot/1.0)",
}
REQUEST_TIMEOUT_SECONDS = 10
REQUEST_DELAY_SECONDS = 0.5
PROGRESS_INTERVAL = 100

TRAINING_FIELDNAMES = [
    "player_name",
    "national_team",
    "club_name",
    "club_wikipedia_url",
    "club_country",
    "start_age_est",
    "end_age_est",
    "start_year_est",
    "end_year_est",
    "source_primary",
    "source_secondary",
    "confidence",
    "notes",
]

MISSING_FIELDNAMES = [
    "player_name",
    "national_team",
    "player_wikipedia_url",
    "status",
    "notes",
]


def clean_text(text: str) -> str:
    text = re.sub(r"\[\s*\d+\s*\]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def safe_int(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


def fetch_soup(session: requests.Session, url: str) -> BeautifulSoup:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def extract_birth_year(infobox: Tag) -> int | None:
    bday = infobox.select_one(".bday")
    if bday:
        match = re.search(r"(\d{4})-\d{2}-\d{2}", bday.get_text(" ", strip=True))
        if match:
            return int(match.group(1))

    for row in infobox.find_all("tr"):
        text = clean_text(row.get_text(" ", strip=True))
        if text.startswith("Date of birth"):
            match = re.search(r"(\d{4})-\d{2}-\d{2}", text)
            if match:
                return int(match.group(1))
            match = re.search(r"\b(19|20)\d{2}\b", text)
            if match:
                return int(match.group(0))
    return None


def parse_year_span(years_text: str) -> tuple[int | None, int | None]:
    full_years = [int(year) for year in re.findall(r"\b(?:19|20)\d{2}\b", years_text)]
    if not full_years:
        return None, None
    if len(full_years) == 1:
        return full_years[0], full_years[0]
    return full_years[0], full_years[-1]


def extract_youth_rows(infobox: Tag) -> list[dict[str, str]]:
    rows = infobox.find_all("tr")
    youth_rows: list[dict[str, str]] = []
    in_youth_section = False

    for row in rows:
        text = clean_text(row.get_text(" ", strip=True))

        if not in_youth_section:
            if text == "Youth career":
                in_youth_section = True
            continue

        if text.startswith("Senior career") or text.startswith("International career"):
            break

        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) < 2:
            continue

        years_text = clean_text(cells[0].get_text(" ", strip=True))
        club_text = clean_text(cells[1].get_text(" ", strip=True))
        if not club_text:
            continue

        club_link = cells[1].find("a", href=True) if len(cells) >= 2 else None
        club_url = ""
        if club_link:
            href = club_link["href"].strip()
            if href and not href.startswith("#"):
                club_url = urljoin("https://en.wikipedia.org/", href)
        youth_rows.append(
            {
                "years_text": years_text,
                "club_name": club_text,
                "club_wikipedia_url": club_url,
            }
        )

    return youth_rows


def clip_to_age_window(
    birth_year: int | None,
    start_year: int | None,
    end_year: int | None,
) -> tuple[str, str, str, str] | None:
    if birth_year is None or start_year is None or end_year is None:
        return None

    start_age = start_year - birth_year
    end_age = end_year - birth_year

    clipped_start_age = max(5, start_age)
    clipped_end_age = min(16, end_age)

    if clipped_start_age > clipped_end_age:
        return None

    clipped_start_year = birth_year + clipped_start_age
    clipped_end_year = birth_year + clipped_end_age

    return (
        str(clipped_start_age),
        str(clipped_end_age),
        str(clipped_start_year),
        str(clipped_end_year),
    )


def main() -> None:
    players: dict[tuple[str, str], dict[str, str]] = {}

    with LINEUPS_CSV.open("r", encoding="utf-8-sig", newline="") as infile:
        reader = csv.DictReader(infile)
        for row in reader:
            player_name = (row.get("player_name") or "").strip()
            national_team = (row.get("team_name") or "").strip()
            player_url = (row.get("player_wikipedia_url") or "").strip()
            if not player_name or not national_team:
                continue
            players[(player_name, national_team)] = {
                "player_name": player_name,
                "national_team": national_team,
                "player_wikipedia_url": player_url,
            }

    training_rows: list[dict[str, str]] = []
    missing_rows: list[dict[str, str]] = []
    ordered_players = sorted(players.values(), key=lambda item: (item["national_team"], item["player_name"]))

    session = requests.Session()
    session.headers.update(HEADERS)

    for index, player in enumerate(ordered_players, start=1):
        player_name = player["player_name"]
        national_team = player["national_team"]
        player_url = player["player_wikipedia_url"]

        if index % PROGRESS_INTERVAL == 0 or index == 1 or index == len(ordered_players):
            print(f"Processed {index}/{len(ordered_players)} player pages...", flush=True)

        if not player_url:
            missing_rows.append(
                {
                    "player_name": player_name,
                    "national_team": national_team,
                    "player_wikipedia_url": "",
                    "status": "missing_player_page",
                    "notes": "No linked Wikipedia player page in lineup table.",
                }
            )
            continue

        try:
            soup = fetch_soup(session, player_url)
            time.sleep(REQUEST_DELAY_SECONDS)
        except requests.RequestException as exc:
            missing_rows.append(
                {
                    "player_name": player_name,
                    "national_team": national_team,
                    "player_wikipedia_url": player_url,
                    "status": "fetch_error",
                    "notes": str(exc),
                }
            )
            continue

        infobox = soup.select_one("table.infobox")
        if infobox is None:
            missing_rows.append(
                {
                    "player_name": player_name,
                    "national_team": national_team,
                    "player_wikipedia_url": player_url,
                    "status": "missing_infobox",
                    "notes": "Wikipedia page does not have a parseable infobox.",
                }
            )
            continue

        birth_year = extract_birth_year(infobox)
        youth_rows = extract_youth_rows(infobox)

        if not youth_rows:
            missing_rows.append(
                {
                    "player_name": player_name,
                    "national_team": national_team,
                    "player_wikipedia_url": player_url,
                    "status": "missing_youth_section",
                    "notes": "No parseable Youth career section found in the infobox.",
                }
            )
            continue

        added_rows = 0
        for youth_row in youth_rows:
            years_text = youth_row["years_text"]
            club_text = youth_row["club_name"]
            start_year, end_year = parse_year_span(years_text)
            clipped = clip_to_age_window(birth_year, start_year, end_year)
            if clipped is None:
                continue

            start_age_est, end_age_est, start_year_est, end_year_est = clipped
            training_rows.append(
                {
                    "player_name": player_name,
                    "national_team": national_team,
                    "club_name": club_text,
                    "club_wikipedia_url": youth_row["club_wikipedia_url"],
                    "club_country": "",
                    "start_age_est": start_age_est,
                    "end_age_est": end_age_est,
                    "start_year_est": start_year_est,
                    "end_year_est": end_year_est,
                    "source_primary": "Wikipedia player infobox",
                    "source_secondary": player_url,
                    "confidence": "medium",
                    "notes": f"First-pass youth record from Wikipedia. Original youth span: {years_text}. Club country still needs backfill.",
                }
            )
            added_rows += 1

        if added_rows == 0:
            fallback_row = youth_rows[0]
            if fallback_row["club_name"]:
                training_rows.append(
                    {
                        "player_name": player_name,
                        "national_team": national_team,
                        "club_name": fallback_row["club_name"],
                        "club_wikipedia_url": fallback_row["club_wikipedia_url"],
                        "club_country": "",
                        "start_age_est": "",
                        "end_age_est": "",
                        "start_year_est": "",
                        "end_year_est": "",
                        "source_primary": "Wikipedia player infobox",
                        "source_secondary": player_url,
                        "confidence": "low",
                        "notes": "Fallback youth record from the earliest listed youth club in the Wikipedia infobox. Exact overlap with ages 5-16 is not published clearly enough to estimate.",
                    }
                )
            else:
                missing_rows.append(
                    {
                        "player_name": player_name,
                        "national_team": national_team,
                        "player_wikipedia_url": player_url,
                        "status": "no_5_16_overlap",
                        "notes": "Youth rows were found, but none overlapped the 5-16 age window after estimation.",
                    }
                )

    training_rows.sort(key=lambda row: (row["national_team"], row["player_name"], safe_int(row["start_year_est"]) or 0, row["club_name"]))
    missing_rows.sort(key=lambda row: (row["national_team"], row["player_name"]))

    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=TRAINING_FIELDNAMES)
        writer.writeheader()
        writer.writerows(training_rows)

    with MISSING_CSV.open("w", encoding="utf-8", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=MISSING_FIELDNAMES)
        writer.writeheader()
        writer.writerows(missing_rows)

    print(f"Wrote {len(training_rows)} youth-club rows to {OUTPUT_CSV}")
    print(f"Wrote {len(missing_rows)} unresolved player rows to {MISSING_CSV}")


if __name__ == "__main__":
    main()
