"""
Second-pass youth research: Wikipedia article text, Transfermarkt, and club-country backfill.
"""
from __future__ import annotations

import csv
import re
import time
from pathlib import Path
from urllib.parse import quote, urljoin, unquote

import requests
from bs4 import BeautifulSoup, Tag

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backfill_club_countries import extract_country_from_page, infer_country_from_text, normalize_club_url


ROOT = Path(__file__).resolve().parents[2]
TRAINING_CSV = ROOT / "data" / "player_youth_training.csv"
MISSING_CSV = ROOT / "data" / "player_youth_training_missing.csv"
LOOKUP_CSV = ROOT / "data" / "club_country_lookup.csv"
MANUAL_CSV = ROOT / "data" / "manual_youth_research.csv"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CursorResearchBot/1.0)"}
REQUEST_TIMEOUT = 15
REQUEST_DELAY = 0.6

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

YOUTH_SECTION_HEADERS = {
    "youth career",
    "youth team",
    "youth clubs",
}

BODY_YOUTH_PATTERNS = [
    re.compile(
        r"began (?:his|her|their) career within the youth system of\s+(.{3,80}?)(?:\s*,|\s+eventually|\.)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:a )?youth product of (?:his |her )?hometown club,?\s+(.{3,80}?)"
        r"(?:\s*,|\s+where|\s+made|\s+who|\s+before|\.)",
        re.IGNORECASE,
    ),
    re.compile(
        r"joined (?:the )?youth academy of (?:his |her )?hometown club,?\s+(.{3,80}?)"
        r"(?:\s+in\s+(\d{4}))?",
        re.IGNORECASE,
    ),
    re.compile(
        r"At the age of (\d{1,2}),?\s+(?:.*?\s+)?joined (?:the )?youth teams of\s+(.{3,80}?)"
        r"(?:\s+in|\s+on|\s*,|\s+and|\.)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:youth academy of|youth teams of|youth setup of|youth system of)\s+(.{3,80}?)"
        r"(?:\s+in\s+(\d{4}))?",
        re.IGNORECASE,
    ),
    re.compile(
        r"joined (?:the )?(.{3,80}?)\s+youth academy\s+in\s+(\d{4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"came through the youth ranks at\s+(.{3,80}?)(?:\s+in\s+(\d{4}))?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:joined|entered|started (?:at|in|with)|came through|progressed through|"
        r"developed (?:at|in|with)|began (?:his|her|their) (?:football )?career (?:at|with)|"
        r"came up through|trained at|started playing (?:for|at|with))\s+"
        r"(?:the youth academy of\s+)?(?:his hometown club,?\s+)?"
        r"(?:the youth teams of\s+)?(.{3,80}?)"
        r"(?:\s+youth academy|\s+academy|\s+youth teams?|\s+in\s+(\d{4})|\s*,|\.)",
        re.IGNORECASE,
    ),
]

CLUB_TRIM_SUFFIXES = re.compile(
    r"\s+(?:youth academy|academy|youth teams?|youth setup|youth system|"
    r"where he|where she|before|after|and|who|which|that|while|making|"
    r"featuring|playing|where|with|from|on|at|in|to|as|for)\b.*$",
    re.IGNORECASE,
)


def read_csv(path: Path) -> list[dict[str, str]]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="") as infile:
                return list(csv.DictReader(infile))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not decode {path}")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


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
    response = session.get(url, timeout=REQUEST_TIMEOUT)
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
    years_text = years_text.strip()
    end_only = re.match(r"^\((?:-)?(\d{1,2}/)?(\d{4})\)$", years_text)
    if end_only:
        return None, int(end_only.group(2))

    start_only = re.match(r"^\(-(\d{4})\)$", years_text)
    if start_only:
        return None, int(start_only.group(1))

    range_match = re.search(r"\((\d{4})\s*-\s*(\d{4})\)", years_text)
    if range_match:
        return int(range_match.group(1)), int(range_match.group(2))

    end_in_paren = re.search(r"\(-(\d{1,2}/)?(\d{4})\)", years_text)
    if end_in_paren and not re.search(r"\(\d{4}\s*-", years_text):
        return None, int(end_in_paren.group(2))

    full_years = [int(year) for year in re.findall(r"\b(?:19|20)\d{2}\b", years_text)]
    if not full_years:
        return None, None
    if len(full_years) == 1:
        return full_years[0], full_years[0]
    return full_years[0], full_years[-1]


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


def normalize_club_name(name: str) -> str:
    name = clean_text(name)
    name = CLUB_TRIM_SUFFIXES.sub("", name).strip(" ,.;:")
    name = re.sub(r"^(?:the|his hometown club)\s+", "", name, flags=re.IGNORECASE)
    return name.strip()


def extract_youth_rows_infobox(infobox: Tag) -> list[dict[str, str]]:
    rows = infobox.find_all("tr")
    youth_rows: list[dict[str, str]] = []
    in_youth_section = False

    for row in rows:
        text = clean_text(row.get_text(" ", strip=True))

        if not in_youth_section:
            header = text.lower()
            if header in YOUTH_SECTION_HEADERS or header.startswith("youth team #"):
                in_youth_section = True
            continue

        if text.startswith("Senior career") or text.startswith("International career"):
            break
        if text.startswith("College career"):
            break

        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) < 2:
            continue

        years_text = clean_text(cells[0].get_text(" ", strip=True))
        club_text = clean_text(cells[1].get_text(" ", strip=True))
        if not club_text:
            continue

        club_link = cells[1].find("a", href=True)
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


def extract_early_career_section(soup: BeautifulSoup) -> str:
    content = soup.select_one("#mw-content-text")
    if content is None:
        return ""

    chunks: list[str] = []
    stop_sections = {
        "international career",
        "career statistics",
        "honours",
        "honors",
        "personal life",
        "see also",
        "references",
        "external links",
    }
    active = False
    club_paragraphs = 0

    for element in content.find_all(["h2", "h3", "p", "li"]):
        if element.name in {"h2", "h3"}:
            title = clean_text(element.get_text(" ", strip=True)).lower()
            if title in stop_sections:
                if active:
                    break
                continue
            if title in {"early career", "youth career", "background"}:
                active = True
                continue
            if title == "club career":
                active = True
                club_paragraphs = 0
                continue
            if active and title not in {"", "club career"}:
                break
            continue

        if active and element.name in {"p", "li"}:
            chunks.append(clean_text(element.get_text(" ", strip=True)))
            club_paragraphs += 1
            if club_paragraphs >= 4:
                break

    if not chunks:
        for paragraph in content.select("p")[:3]:
            chunks.append(clean_text(paragraph.get_text(" ", strip=True)))
    return " ".join(chunks)


def extract_youth_from_body(text: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for pattern in BODY_YOUTH_PATTERNS:
        for match in pattern.finditer(text):
            groups = match.groups()
            club_name = ""
            start_year = ""
            start_age = ""

            if len(groups) == 1:
                club_name = normalize_club_name(groups[0])
            elif len(groups) == 2:
                if groups[0].isdigit():
                    start_age = groups[0]
                    club_name = normalize_club_name(groups[1])
                elif groups[1] and groups[1].isdigit():
                    club_name = normalize_club_name(groups[0])
                    start_year = groups[1]
                else:
                    club_name = normalize_club_name(groups[0])
                    if groups[1]:
                        start_year = groups[1]

            club_name = normalize_club_name(club_name)
            if len(club_name) < 3 or len(club_name.split()) > 8:
                continue
            if any(
                bad in club_name.lower()
                for bad in ("professional", "footballer", "national team", "world cup", "debut")
            ):
                continue

            key = (club_name.lower(), start_year)
            if key in seen:
                continue
            seen.add(key)

            years_text = start_year or ""
            findings.append(
                {
                    "years_text": years_text,
                    "club_name": club_name,
                    "club_wikipedia_url": "",
                    "start_age_hint": start_age,
                }
            )
    return findings


def find_transfermarkt_url(soup: BeautifulSoup) -> str:
    for link in soup.select("a[href*='transfermarkt']"):
        href = link.get("href", "")
        if "/profil/spieler/" in href or "/spieler/" in href:
            return href.split("?")[0]
    return ""


def parse_transfermarkt_youth_block(block: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for part in re.split(r",\s*(?=[A-Za-zÀ-ÿ])", block):
        part = part.strip()
        if not part:
            continue
        year_match = re.search(r"\(([^)]+)\)", part)
        years_text = ""
        club_name = part
        if year_match:
            years_text = year_match.group(1).strip()
            club_name = part[: year_match.start()].strip()
        club_name = normalize_club_name(club_name)
        if club_name:
            rows.append(
                {
                    "years_text": years_text,
                    "club_name": club_name,
                    "club_wikipedia_url": "",
                    "start_age_hint": "",
                }
            )
    return rows


def extract_early_clubs_from_body(text: str) -> list[dict[str, str]]:
    match = re.search(
        r"After playing for\s+(.{3,120}?)(?:,\s*he|\s+he\s+signed|\s+signed|\.)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return []

    club_blob = match.group(1)
    clubs = re.split(r",\s*|\s+and\s+", club_blob)
    rows: list[dict[str, str]] = []
    for club in clubs:
        club_name = normalize_club_name(club)
        if len(club_name) >= 3:
            rows.append(
                {
                    "years_text": "",
                    "club_name": club_name,
                    "club_wikipedia_url": "",
                    "start_age_hint": "",
                }
            )
    return rows


def extract_senior_debut_youth(infobox: Tag, birth_year: int | None) -> list[dict[str, str]]:
    if infobox is None or birth_year is None:
        return []

    in_senior = False
    for row in infobox.find_all("tr"):
        text = clean_text(row.get_text(" ", strip=True))
        if text == "Senior career*":
            in_senior = True
            continue
        if not in_senior:
            continue
        if text.startswith("International career"):
            break

        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) < 2:
            continue

        years_text = clean_text(cells[0].get_text(" ", strip=True))
        club_text = clean_text(cells[1].get_text(" ", strip=True))
        if not club_text or years_text.startswith("Years"):
            continue

        start_year, _ = parse_year_span(years_text.replace("–", "-"))
        if start_year is None:
            year_match = re.search(r"(\d{4})", years_text)
            if year_match:
                start_year = int(year_match.group(1))

        if start_year is None:
            continue

        debut_age = start_year - birth_year
        if debut_age > 18:
            break

        club_link = cells[1].find("a", href=True)
        club_url = ""
        if club_link:
            href = club_link["href"].strip()
            if href and not href.startswith("#"):
                club_url = urljoin("https://en.wikipedia.org/", href)

        return [
            {
                "years_text": years_text,
                "club_name": club_text,
                "club_wikipedia_url": club_url,
                "start_age_hint": str(max(5, debut_age - 3)),
            }
        ]
    return []


def extract_youth_from_transfermarkt(session: requests.Session, tm_url: str) -> list[dict[str, str]]:
    try:
        soup = fetch_soup(session, tm_url)
        time.sleep(REQUEST_DELAY)
    except requests.RequestException:
        return []

    for heading in soup.select("h2.content-box-headline"):
        if "youth" not in heading.get_text(" ", strip=True).lower():
            continue
        sibling = heading.find_next_sibling()
        if sibling is None:
            sibling = heading.find_next(["p", "div", "span"])
        if sibling is None:
            continue
        block = sibling.get_text(" ", strip=True)
        if block:
            return parse_transfermarkt_youth_block(block)
    return []


def search_transfermarkt(session: requests.Session, player_name: str) -> str:
    query = quote(player_name)
    search_url = f"https://www.transfermarkt.com/schnellsuche/ergebnis/schnellsuche?query={query}"
    try:
        response = session.get(search_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        time.sleep(REQUEST_DELAY)
    except requests.RequestException:
        return ""

    soup = BeautifulSoup(response.text, "html.parser")
    for row in soup.select("table.items tbody tr"):
        link = row.select_one("td.hauptlink a[href*='/profil/spieler/']")
        if link:
            return urljoin("https://www.transfermarkt.com", link["href"]).split("?")[0]
    return ""


def resolve_club_wikipedia_url(session: requests.Session, club_name: str) -> str:
    api_url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "opensearch",
        "search": club_name,
        "limit": 3,
        "namespace": 0,
        "format": "json",
    }
    try:
        response = session.get(api_url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        time.sleep(0.2)
    except (requests.RequestException, ValueError):
        return ""

    if len(data) < 4 or not data[3]:
        return ""
    return data[3][0]


def infer_club_country_from_name(club_name: str, national_team: str) -> str:
    name = club_name.lower()
    country_hints = [
        (r"\bfc\b|\bsc\b|\bas\b|\bsk\b|\bbk\b|\bif\b|\bcf\b|\bac\b", ""),
    ]
    _ = country_hints
    if infer_country_from_text(name):
        return infer_country_from_text(name)

    national_map = {
        "United States": "United States",
        "USA": "United States",
        "Colombia": "Colombia",
        "Norway": "Norway",
        "Panama": "Panama",
        "Egypt": "Egypt",
        "Ghana": "Ghana",
        "Haiti": "Haiti",
        "Iraq": "Iraq",
        "Jordan": "Jordan",
        "Mexico": "Mexico",
        "Paraguay": "Paraguay",
        "Qatar": "Qatar",
        "Saudi Arabia": "Saudi Arabia",
        "Senegal": "Senegal",
        "South Africa": "South Africa",
        "Tunisia": "Tunisia",
        "Uruguay": "Uruguay",
        "Uzbekistan": "Uzbekistan",
        "Cabo Verde": "Cabo Verde",
        "Czechia": "Czechia",
        "Bosnia and Herzegovina": "Bosnia and Herzegovina",
    }
    return national_map.get(national_team, "")


def choose_best_source(
    sources: list[tuple[str, list[dict[str, str]]]],
) -> tuple[str, list[dict[str, str]]]:
    by_name = {name: rows for name, rows in sources}
    transfermarkt = by_name.get("Transfermarkt", [])
    infobox = by_name.get("Wikipedia player infobox", [])
    body = by_name.get("Wikipedia article text", [])
    early = by_name.get("Wikipedia early clubs", [])
    senior = by_name.get("Wikipedia senior debut inference", [])

    if transfermarkt and any(row.get("years_text") for row in transfermarkt):
        return "Transfermarkt", transfermarkt
    if infobox:
        return "Wikipedia player infobox", infobox
    if body and any(row.get("years_text") for row in body):
        return "Wikipedia article text", body
    if transfermarkt:
        return "Transfermarkt", transfermarkt
    if body:
        return "Wikipedia article text", body
    if early:
        return "Wikipedia early clubs", early
    if senior:
        return "Wikipedia senior debut inference", senior
    return sources[0]


def load_manual_research() -> dict[tuple[str, str], list[dict[str, str]]]:
    manual: dict[tuple[str, str], list[dict[str, str]]] = {}
    if not MANUAL_CSV.exists():
        return manual
    for row in read_csv(MANUAL_CSV):
        key = (row["player_name"].strip(), row["national_team"].strip())
        manual.setdefault(key, []).append(row)
    return manual


def manual_rows_to_training(
    player_name: str,
    national_team: str,
    manual_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for row in manual_rows:
        output.append(
            {
                "player_name": player_name,
                "national_team": national_team,
                "club_name": row.get("club_name", "").strip(),
                "club_wikipedia_url": row.get("club_wikipedia_url", "").strip(),
                "club_country": "",
                "start_age_est": "",
                "end_age_est": "",
                "start_year_est": row.get("start_year_est", "").strip(),
                "end_year_est": row.get("end_year_est", "").strip(),
                "source_primary": row.get("source_primary", "Manual research").strip(),
                "source_secondary": row.get("source_secondary", "").strip(),
                "confidence": row.get("confidence", "low").strip(),
                "notes": row.get("notes", "Manual second-pass research entry.").strip(),
            }
        )
    return output


def apply_manual_age_estimates(
    training_rows: list[dict[str, str]],
    birth_year: int | None,
) -> None:
    if birth_year is None:
        return
    for row in training_rows:
        if row.get("start_age_est"):
            continue
        start_year = safe_int(row.get("start_year_est"))
        end_year = safe_int(row.get("end_year_est"))
        clipped = clip_to_age_window(birth_year, start_year, end_year)
        if clipped is None:
            continue
        row["start_age_est"], row["end_age_est"], row["start_year_est"], row["end_year_est"] = clipped


def load_club_country_cache() -> dict[str, str]:
    cache: dict[str, str] = {}
    if not LOOKUP_CSV.exists():
        return cache
    for row in read_csv(LOOKUP_CSV):
        club_url = normalize_club_url(row.get("club_wikipedia_url", ""))
        country = (row.get("club_country") or "").strip()
        if club_url and country:
            cache[club_url] = country
    return cache


def build_training_rows(
    player_name: str,
    national_team: str,
    birth_year: int | None,
    youth_rows: list[dict[str, str]],
    source_primary: str,
    source_secondary: str,
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    added = 0

    for youth_row in youth_rows:
        years_text = youth_row.get("years_text", "")
        club_text = youth_row.get("club_name", "")
        start_age_hint = youth_row.get("start_age_hint", "")

        start_year, end_year = parse_year_span(years_text)
        if start_year is None and end_year is not None and birth_year:
            start_year = birth_year + 5
        if start_year is None and start_age_hint and birth_year:
            age = safe_int(start_age_hint)
            if age is not None:
                start_year = birth_year + age
                end_year = start_year

        clipped = clip_to_age_window(birth_year, start_year, end_year)
        if clipped is None:
            continue

        start_age_est, end_age_est, start_year_est, end_year_est = clipped
        output.append(
            {
                "player_name": player_name,
                "national_team": national_team,
                "club_name": club_text,
                "club_wikipedia_url": youth_row.get("club_wikipedia_url", ""),
                "club_country": "",
                "start_age_est": start_age_est,
                "end_age_est": end_age_est,
                "start_year_est": start_year_est,
                "end_year_est": end_year_est,
                "source_primary": source_primary,
                "source_secondary": source_secondary,
                "confidence": "medium" if years_text else "low",
                "notes": (
                    f"Second-pass research. Original span: {years_text or 'unknown'}. "
                    f"Club country pending backfill."
                ),
            }
        )
        added += 1

    if added == 0 and youth_rows:
        fallback = youth_rows[0]
        if fallback.get("club_name"):
            output.append(
                {
                    "player_name": player_name,
                    "national_team": national_team,
                    "club_name": fallback["club_name"],
                    "club_wikipedia_url": fallback.get("club_wikipedia_url", ""),
                    "club_country": "",
                    "start_age_est": "",
                    "end_age_est": "",
                    "start_year_est": "",
                    "end_year_est": "",
                    "source_primary": source_primary,
                    "source_secondary": source_secondary,
                    "confidence": "low",
                    "notes": (
                        "Second-pass research fallback. Club identified but ages 5-16 "
                        "overlap could not be estimated reliably."
                    ),
                }
            )
    return output


def research_player(
    session: requests.Session,
    player_name: str,
    national_team: str,
    player_url: str,
    manual_lookup: dict[tuple[str, str], list[dict[str, str]]] | None = None,
) -> tuple[list[dict[str, str]], str]:
    try:
        soup = fetch_soup(session, player_url)
        time.sleep(REQUEST_DELAY)
    except requests.RequestException as exc:
        return [], f"fetch_error: {exc}"

    infobox = soup.select_one("table.infobox")
    birth_year = extract_birth_year(infobox) if infobox else None

    sources: list[tuple[str, list[dict[str, str]]]] = []

    if infobox:
        infobox_rows = extract_youth_rows_infobox(infobox)
        if infobox_rows:
            sources.append(("Wikipedia player infobox", infobox_rows))

    body_text = extract_early_career_section(soup)
    body_rows = extract_youth_from_body(body_text)
    if body_rows:
        sources.append(("Wikipedia article text", body_rows))

    early_clubs = extract_early_clubs_from_body(body_text)
    if early_clubs:
        sources.append(("Wikipedia early clubs", early_clubs))

    senior_youth = extract_senior_debut_youth(infobox, birth_year) if infobox else []
    if senior_youth:
        sources.append(("Wikipedia senior debut inference", senior_youth))

    tm_url = find_transfermarkt_url(soup)
    if not tm_url:
        tm_url = search_transfermarkt(session, player_name)
    if tm_url:
        tm_rows = extract_youth_from_transfermarkt(session, tm_url)
        if tm_rows:
            sources.append(("Transfermarkt", tm_rows))

    manual_rows = (manual_lookup or {}).get((player_name, national_team), [])

    if not sources:
        if manual_rows:
            manual_training = manual_rows_to_training(player_name, national_team, manual_rows)
            apply_manual_age_estimates(manual_training, birth_year)
            if manual_training:
                return manual_training, "resolved_manual"
        return [], "no_youth_data_found"

    best_source, best_rows = choose_best_source(sources)

    secondary = player_url
    if best_source == "Transfermarkt" and tm_url:
        secondary = tm_url

    for row in best_rows:
        if not row.get("club_wikipedia_url"):
            row["club_wikipedia_url"] = resolve_club_wikipedia_url(session, row["club_name"])

    training_rows = build_training_rows(
        player_name,
        national_team,
        birth_year,
        best_rows,
        best_source,
        secondary,
    )
    if training_rows:
        return training_rows, "resolved"

    manual_rows = (manual_lookup or {}).get((player_name, national_team), [])
    if manual_rows:
        manual_training = manual_rows_to_training(player_name, national_team, manual_rows)
        apply_manual_age_estimates(manual_training, birth_year)
        if manual_training:
            return manual_training, "resolved_manual"

    return [], "no_5_16_overlap"


def backfill_countries(session: requests.Session, rows: list[dict[str, str]]) -> None:
    club_cache = load_club_country_cache()
    urls_to_fetch = sorted(
        {
            normalize_club_url(row.get("club_wikipedia_url", ""))
            for row in rows
            if not row.get("club_country", "").strip()
            and normalize_club_url(row.get("club_wikipedia_url", ""))
            and normalize_club_url(row.get("club_wikipedia_url", "")) not in club_cache
        }
    )

    for index, club_url in enumerate(urls_to_fetch, start=1):
        try:
            club_cache[club_url] = extract_country_from_page(session, club_url)
            time.sleep(REQUEST_DELAY)
        except requests.RequestException:
            club_cache[club_url] = ""
        if index % 50 == 0 or index == len(urls_to_fetch):
            print(f"  Fetched {index}/{len(urls_to_fetch)} new club pages...", flush=True)

    for row in rows:
        if row.get("club_country", "").strip():
            continue
        club_url = normalize_club_url(row.get("club_wikipedia_url", ""))
        row["club_wikipedia_url"] = club_url
        country = club_cache.get(club_url, "")
        if not country:
            country = infer_club_country_from_name(row.get("club_name", ""), row.get("national_team", ""))
        row["club_country"] = country


def upgrade_low_confidence_rows(
    session: requests.Session,
    rows: list[dict[str, str]],
    existing_keys: set[tuple[str, str, str]],
    manual_lookup: dict[tuple[str, str], list[dict[str, str]]],
) -> int:
    low_players: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        if row.get("confidence") == "low" and not row.get("start_age_est", "").strip():
            key = (row["player_name"], row["national_team"])
            if key not in low_players:
                low_players[key] = row

    added = 0
    for (player_name, national_team), existing_row in sorted(low_players.items()):
        player_url = existing_row.get("source_secondary", "")
        if not player_url.startswith("https://en.wikipedia.org/"):
            continue

        new_rows, status = research_player(
            session, player_name, national_team, player_url, manual_lookup
        )
        if status not in {"resolved", "resolved_manual"}:
            continue

        for new_row in new_rows:
            if not new_row.get("start_age_est"):
                continue
            dedupe_key = (player_name, national_team, new_row["club_name"].lower())
            if dedupe_key in existing_keys:
                for row in rows:
                    if (
                        row["player_name"] == player_name
                        and row["national_team"] == national_team
                        and row["club_name"].lower() == new_row["club_name"].lower()
                        and row.get("confidence") == "low"
                        and not row.get("start_age_est")
                    ):
                        row.update(
                            {
                                "start_age_est": new_row["start_age_est"],
                                "end_age_est": new_row["end_age_est"],
                                "start_year_est": new_row["start_year_est"],
                                "end_year_est": new_row["end_year_est"],
                                "confidence": new_row["confidence"],
                                "source_primary": new_row["source_primary"],
                                "notes": new_row["notes"],
                            }
                        )
                        added += 1
            else:
                rows.append(new_row)
                existing_keys.add(dedupe_key)
                added += 1
    return added


def main() -> None:
    training_rows = read_csv(TRAINING_CSV)
    missing_rows = read_csv(MISSING_CSV)

    session = requests.Session()
    session.headers.update(HEADERS)

    existing_keys = {
        (r["player_name"], r["national_team"], r["club_name"].lower()) for r in training_rows
    }

    resolved_missing: list[dict[str, str]] = []
    still_missing: list[dict[str, str]] = []

    manual_lookup = load_manual_research()

    print(f"Researching {len(missing_rows)} missing players...", flush=True)
    for index, player in enumerate(missing_rows, start=1):
        player_name = player["player_name"]
        national_team = player["national_team"]
        player_url = player.get("player_wikipedia_url", "").strip()

        if index % 10 == 0 or index == 1:
            print(
                f"  Missing player {index}/{len(missing_rows)}: "
                f"{player_name.encode('ascii', 'replace').decode()}",
                flush=True,
            )

        if not player_url:
            still_missing.append(player)
            continue

        new_rows, status = research_player(
            session, player_name, national_team, player_url, manual_lookup
        )
        if new_rows:
            for row in new_rows:
                key = (player_name, national_team, row["club_name"].lower())
                if key not in existing_keys:
                    training_rows.append(row)
                    existing_keys.add(key)
            resolved_missing.append(player)
        else:
            still_missing.append(
                {
                    **player,
                    "status": status if status not in {"resolved", "resolved_manual"} else player.get("status", ""),
                    "notes": (
                        f"Second-pass research ({status}). "
                        + player.get("notes", "")
                    ).strip(),
                }
            )

    print(f"Resolved {len(resolved_missing)} previously missing players", flush=True)

    upgraded = upgrade_low_confidence_rows(session, training_rows, existing_keys, manual_lookup)
    print(f"Upgraded {upgraded} low-confidence rows with age estimates", flush=True)

    print("Backfilling club countries...", flush=True)
    backfill_countries(session, training_rows)

    training_rows.sort(
        key=lambda row: (
            row["national_team"],
            row["player_name"],
            safe_int(row["start_year_est"]) or 0,
            row["club_name"],
        )
    )
    still_missing.sort(key=lambda row: (row["national_team"], row["player_name"]))

    write_csv(TRAINING_CSV, TRAINING_FIELDNAMES, training_rows)
    write_csv(MISSING_CSV, MISSING_FIELDNAMES, still_missing)

    filled_country = sum(1 for r in training_rows if r.get("club_country", "").strip())
    print(f"Wrote {len(training_rows)} training rows ({filled_country} with club country)")
    print(f"Wrote {len(still_missing)} unresolved missing rows (was {len(missing_rows)})")


if __name__ == "__main__":
    main()
