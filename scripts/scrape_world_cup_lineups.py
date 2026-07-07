import csv
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_CSV = ROOT / "data" / "world_cup_match_lineups.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CursorResearchBot/1.0)",
}

GROUP_PAGES = [
    f"https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_Group_{letter}"
    for letter in "ABCDEFGHIJKL"
]
KNOCKOUT_PAGE = "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_knockout_stage"
PAGE_URLS = GROUP_PAGES + [KNOCKOUT_PAGE]

KNOWN_POSITIONS = {
    "GK",
    "RB",
    "LB",
    "CB",
    "RWB",
    "LWB",
    "DM",
    "CM",
    "RM",
    "LM",
    "AM",
    "RW",
    "LW",
    "RF",
    "LF",
    "CF",
    "FW",
    "MF",
    "DF",
}

FIELDNAMES = [
    "match_id",
    "match_date",
    "stage",
    "team_name",
    "opponent_name",
    "player_name",
    "player_wikipedia_url",
    "player_position",
    "starter",
    "source_primary",
    "source_secondary",
    "source_notes",
]

STANDARD_TEAM_NAMES = {
    "Cape Verde": "Cabo Verde",
    "Czech Republic": "Czechia",
    "Iran": "IR Iran",
    "Ivory Coast": "Côte d'Ivoire",
    "South Korea": "Korea Republic",
    "Turkey": "Türkiye",
    "United States": "USA",
}


def fetch_soup(url: str) -> BeautifulSoup:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def clean_text(text: str) -> str:
    text = re.sub(r"\[\s*\d+\s*\]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def sanitize_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return slug.strip("-")


def normalize_team_name(name: str) -> str:
    return STANDARD_TEAM_NAMES.get(name, name)


def extract_stage(match_heading: Tag, page_title: str) -> str:
    if "Group" in page_title:
        match = re.search(r"(Group [A-L])", page_title)
        return match.group(1) if match else page_title

    for sibling in match_heading.previous_siblings:
        if isinstance(sibling, Tag):
            if sibling.name in {"h2", "h3"}:
                text = clean_text(sibling.get_text(" ", strip=True)).replace("[ edit ]", "").strip()
            elif sibling.name == "div" and "mw-heading" in sibling.get("class", []):
                text = clean_text(sibling.get_text(" ", strip=True)).replace("[ edit ]", "").strip()
            else:
                continue
            if text.startswith("Round of") or text in {"Quarter-finals", "Semi-finals", "Third place play-off", "Final"}:
                return text
    return "Knockout stage"


def parse_team_names(header_table: Tag) -> tuple[str, str] | None:
    cells = header_table.find_all("td")
    if len(cells) < 2:
        return None
    left = clean_text(cells[0].get_text(" ", strip=True))
    right = clean_text(cells[1].get_text(" ", strip=True))
    if not left or not right:
        return None
    return left, right


def parse_lineup_table(lineup_table: Tag) -> list[dict[str, str]]:
    starters: list[dict[str, str]] = []

    for row in lineup_table.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if not cells:
            continue

        row_text = clean_text(row.get_text(" ", strip=True))
        if row_text.startswith("Substitutions:"):
            break

        if len(cells) < 3:
            continue

        position = clean_text(cells[0].get_text(" ", strip=True))
        shirt_number = clean_text(cells[1].get_text(" ", strip=True))
        if position not in KNOWN_POSITIONS or not shirt_number.isdigit():
            continue

        name_cell = cells[2]
        player_name = clean_text(name_cell.get_text(" ", strip=True))
        player_name = re.sub(r"\s+\(\s*c\s*\)\s*$", "", player_name, flags=re.IGNORECASE)
        player_link = name_cell.find("a", href=True)
        player_url = urljoin("https://en.wikipedia.org", player_link["href"]) if player_link else ""

        starters.append(
            {
                "player_name": player_name,
                "player_wikipedia_url": player_url,
                "player_position": position,
            }
        )

    return starters


def extract_match_date(match_heading: Tag, fevent_table: Tag) -> str:
    candidate_texts = [fevent_table.get_text(" ", strip=True)]

    for sibling in match_heading.find_next_siblings(limit=8):
        if isinstance(sibling, Tag):
            candidate_texts.append(sibling.get_text(" ", strip=True))

    for text in candidate_texts:
        match = re.search(r"\(\s*(\d{4}-\d{2}-\d{2})\s*\)", text)
        if match:
            return match.group(1)

    return ""


def collect_matches_from_page(url: str) -> list[dict[str, str]]:
    soup = fetch_soup(url)
    page_title = clean_text(soup.title.get_text(" ", strip=True).replace(" - Wikipedia", ""))
    rows: list[dict[str, str]] = []

    for heading_tag in soup.select("h3[id*='_vs_'], h2[id*='_vs_']"):
        match_heading = heading_tag.parent if heading_tag.parent and heading_tag.parent.name == "div" else heading_tag
        stage = extract_stage(match_heading, page_title)

        fevent_table = match_heading.find_next("table", class_="fevent")
        if fevent_table is None:
            continue

        header_table = fevent_table.find_next("table")
        lineup_wrapper_table = header_table.find_next("table") if header_table else None
        left_lineup_table = lineup_wrapper_table.find_next("table") if lineup_wrapper_table else None
        right_lineup_table = left_lineup_table.find_next("table") if left_lineup_table else None

        if header_table is None or lineup_wrapper_table is None or left_lineup_table is None or right_lineup_table is None:
            continue

        team_names = parse_team_names(header_table)
        if team_names is None:
            continue

        left_team, right_team = (normalize_team_name(team_names[0]), normalize_team_name(team_names[1]))
        left_starters = parse_lineup_table(left_lineup_table)
        right_starters = parse_lineup_table(right_lineup_table)

        if len(left_starters) != 11 or len(right_starters) != 11:
            print(
                f"WARNING: skipping match {match_id!r} — "
                f"parsed {len(left_starters)} left / {len(right_starters)} right starters "
                f"(expected 11 each). Source: {section_url}",
                flush=True,
            )
            continue

        match_date = extract_match_date(match_heading, fevent_table)
        match_id = f"{match_date}_{sanitize_slug(left_team)}_vs_{sanitize_slug(right_team)}"
        section_url = f"{url}#{heading_tag['id']}"

        for starter in left_starters:
            rows.append(
                {
                    "match_id": match_id,
                    "match_date": match_date,
                    "stage": stage,
                    "team_name": left_team,
                    "opponent_name": right_team,
                    "player_name": starter["player_name"],
                    "player_wikipedia_url": starter["player_wikipedia_url"],
                    "player_position": starter["player_position"],
                    "starter": "TRUE",
                    "source_primary": "Wikipedia",
                    "source_secondary": "",
                    "source_notes": section_url,
                }
            )

        for starter in right_starters:
            rows.append(
                {
                    "match_id": match_id,
                    "match_date": match_date,
                    "stage": stage,
                    "team_name": right_team,
                    "opponent_name": left_team,
                    "player_name": starter["player_name"],
                    "player_wikipedia_url": starter["player_wikipedia_url"],
                    "player_position": starter["player_position"],
                    "starter": "TRUE",
                    "source_primary": "Wikipedia",
                    "source_secondary": "",
                    "source_notes": section_url,
                }
            )

    return rows


def main() -> None:
    all_rows: list[dict[str, str]] = []

    for url in PAGE_URLS:
        page_rows = collect_matches_from_page(url)
        print(f"{url} -> {len(page_rows)} starter rows")
        all_rows.extend(page_rows)

    all_rows.sort(key=lambda row: (row["match_date"], row["match_id"], row["team_name"], row["player_name"]))

    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_rows)

    unique_matches = len({row["match_id"] for row in all_rows})
    print(f"Wrote {len(all_rows)} starter rows across {unique_matches} matches to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
