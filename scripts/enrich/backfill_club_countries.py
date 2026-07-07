import csv
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[2]
TRAINING_CSV = ROOT / "data" / "player_youth_training.csv"
LOOKUP_CSV = ROOT / "data" / "club_country_lookup.csv"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CursorResearchBot/1.0)"}
REQUEST_DELAY_SECONDS = 0.5

COUNTRY_PATTERNS = [
    (r"\bbosnia and herzegovina\b|\bbosnian\b", "Bosnia and Herzegovina"),
    (r"\bczech republic\b|\bczechia\b|\bczech\b", "Czechia"),
    (r"\bnew zealand\b|\bnew zealander\b|\bnew zealander\b", "New Zealand"),
    (r"\bsouth africa\b|\bsouth african\b", "South Africa"),
    (r"\bsouth korea\b|\bkorea republic\b|\bsouth korean\b", "South Korea"),
    (r"\bsaudi arabia\b|\bsaudi\b", "Saudi Arabia"),
    (r"\bunited states\b|\bamerican\b", "United States"),
    (r"\bcape verde\b|\bcabo verde\b|\bcape verdean\b", "Cabo Verde"),
    (r"\bcote d'ivoire\b|\bcôte d'ivoire\b|\bivorian\b|\bivory coast\b", "Côte d'Ivoire"),
    (r"\bdr congo\b|\bdemocratic republic of the congo\b|\bcongolese\b", "DR Congo"),
    (r"\bcuracao\b|\bcuraçao\b|\bcuraçaoan\b|\bcuracaoan\b", "Curaçao"),
    (r"\bnorthern ireland\b|\bnorthern irish\b", "Northern Ireland"),
    (r"\brepublic of ireland\b|\birish\b", "Ireland"),
    (r"\bargentina\b|\bargentine\b|\bargentinian\b", "Argentina"),
    (r"\baustralia\b|\baustralian\b", "Australia"),
    (r"\baustria\b|\baustrian\b", "Austria"),
    (r"\bbelgium\b|\bbelgian\b", "Belgium"),
    (r"\bbrazil\b|\bbrazilian\b", "Brazil"),
    (r"\bcanada\b|\bcanadian\b", "Canada"),
    (r"\bcolombia\b|\bcolombian\b", "Colombia"),
    (r"\bcroatia\b|\bcroatian\b", "Croatia"),
    (r"\bdenmark\b|\bdanish\b", "Denmark"),
    (r"\becuador\b|\becuadorean\b|\becuadorian\b", "Ecuador"),
    (r"\begypt\b|\begyptian\b", "Egypt"),
    (r"\bengland\b|\benglish\b", "England"),
    (r"\bfinland\b|\bfinnish\b", "Finland"),
    (r"\bfrance\b|\bfrench\b", "France"),
    (r"\bgermany\b|\bgerman\b", "Germany"),
    (r"\bghana\b|\bghanaian\b", "Ghana"),
    (r"\bgreece\b|\bgreek\b", "Greece"),
    (r"\bhaiti\b|\bhaitian\b", "Haiti"),
    (r"\bhungary\b|\bhungarian\b", "Hungary"),
    (r"\biran\b|\biranian\b", "Iran"),
    (r"\biraq\b|\biraqi\b", "Iraq"),
    (r"\bitaly\b|\bitalian\b", "Italy"),
    (r"\bjapan\b|\bjapanese\b", "Japan"),
    (r"\bjordan\b|\bjordanian\b", "Jordan"),
    (r"\bmorocco\b|\bmarocco\b|\bmoroccan\b", "Morocco"),
    (r"\bnetherlands\b|\bdutch\b", "Netherlands"),
    (r"\bnorway\b|\bnorwegian\b", "Norway"),
    (r"\bpanama\b|\bpanamanian\b", "Panama"),
    (r"\bparaguay\b|\bparaguayan\b", "Paraguay"),
    (r"\bpoland\b|\bpolish\b", "Poland"),
    (r"\bportugal\b|\bportuguese\b", "Portugal"),
    (r"\bqatar\b|\bqatari\b", "Qatar"),
    (r"\bromania\b|\bromanian\b", "Romania"),
    (r"\bscotland\b|\bscottish\b", "Scotland"),
    (r"\bsenegal\b|\bsenegalese\b", "Senegal"),
    (r"\bserbia\b|\bserbian\b", "Serbia"),
    (r"\bslovakia\b|\bslovak\b", "Slovakia"),
    (r"\bslovenia\b|\bslovenian\b", "Slovenia"),
    (r"\bspain\b|\bspanish\b", "Spain"),
    (r"\bsweden\b|\bswedish\b", "Sweden"),
    (r"\bswitzerland\b|\bswiss\b", "Switzerland"),
    (r"\btunisia\b|\btunisian\b", "Tunisia"),
    (r"\bturkey\b|\btürkiye\b|\bturkish\b", "Türkiye"),
    (r"\buruguay\b|\buruguayan\b", "Uruguay"),
    (r"\buzbekistan\b|\buzbek\b|\buzbekistani\b", "Uzbekistan"),
    (r"\bwales\b|\bwelsh\b", "Wales"),
]


def infer_country_from_text(text: str) -> str:
    text = text.lower()
    phrase_templates = [
        r"club in .*?{pattern}",
        r"club from .*?{pattern}",
        r"{pattern} professional football club",
        r"{pattern} football club",
        r"{pattern} sports club",
        r"{pattern} association football club",
    ]
    for pattern, country in COUNTRY_PATTERNS:
        for template in phrase_templates:
            if re.search(template.format(pattern=pattern), text):
                return country
    for pattern, country in COUNTRY_PATTERNS:
        if re.search(pattern, text):
            return country
    return ""


def normalize_club_url(url: str) -> str:
    url = (url or "").strip()
    if not url or "#cite" in url:
        return ""
    if "/wiki/" not in url:
        return urljoin("https://en.wikipedia.org/", url)
    suffix = url.split("/wiki/", 1)[1]
    return f"https://en.wikipedia.org/wiki/{suffix}"


def extract_country_from_page(session: requests.Session, club_url: str) -> str:
    response = session.get(club_url, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    sections = soup.select(".mw-parser-output > section")
    first_section_text = ""
    if sections:
        first_section_text = " ".join(sections[0].get_text(" ", strip=True).split())
    cutoff_markers = [" This article ", " For ", " Not to be confused ", " You can help "]
    cropped_text = first_section_text
    for marker in cutoff_markers:
        idx = cropped_text.find(marker)
        if idx != -1:
            cropped_text = cropped_text[:idx]
    lead_text = cropped_text[:220].lower()

    category_text = " ".join(
        a.get_text(" ", strip=True)
        for a in soup.select("#mw-normal-catlinks a")[1:]
    ).lower()

    country = infer_country_from_text(lead_text)
    if country:
        return country
    return infer_country_from_text(category_text)


def main() -> None:
    with TRAINING_CSV.open("r", encoding="utf-8-sig", newline="") as infile:
        rows = list(csv.DictReader(infile))
        fieldnames = list(rows[0].keys()) if rows else []

    session = requests.Session()
    session.headers.update(HEADERS)

    club_cache: dict[str, str] = {}

    unique_urls = sorted({normalize_club_url(row.get("club_wikipedia_url", "")) for row in rows if normalize_club_url(row.get("club_wikipedia_url", ""))})

    for index, club_url in enumerate(unique_urls, start=1):
        try:
            club_cache[club_url] = extract_country_from_page(session, club_url)
            time.sleep(REQUEST_DELAY_SECONDS)
        except requests.RequestException:
            club_cache[club_url] = ""

        if index % 100 == 0 or index == 1 or index == len(unique_urls):
            print(f"Resolved {index}/{len(unique_urls)} club pages...", flush=True)

    lookup_rows = []
    for row in rows:
        club_url = normalize_club_url(row.get("club_wikipedia_url", ""))
        row["club_wikipedia_url"] = club_url
        row["club_country"] = club_cache.get(club_url, row.get("club_country", "").strip())
        if row.get("club_name", "").strip():
            lookup_rows.append(
                {
                    "club_name": row["club_name"].strip(),
                    "club_wikipedia_url": club_url,
                    "club_country": row.get("club_country", "").strip(),
                }
            )

    dedup_lookup = {}
    for item in lookup_rows:
        key = (item["club_name"], item["club_wikipedia_url"])
        dedup_lookup[key] = item

    with TRAINING_CSV.open("w", encoding="utf-8", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    with LOOKUP_CSV.open("w", encoding="utf-8", newline="") as outfile:
        fieldnames = ["club_name", "club_wikipedia_url", "club_country"]
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        for item in sorted(dedup_lookup.values(), key=lambda row: (row["club_country"], row["club_name"])):
            writer.writerow(item)

    filled = sum(1 for row in rows if (row.get("club_country") or "").strip())
    print(f"Backfilled club countries for {filled}/{len(rows)} training rows")
    print(f"Wrote lookup table to {LOOKUP_CSV}")


if __name__ == "__main__":
    main()
