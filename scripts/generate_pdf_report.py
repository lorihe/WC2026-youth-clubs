from datetime import datetime
from pathlib import Path
import collections
import csv
import unicodedata

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# Register Arial for Unicode player/club names (always available on Windows)
_ARIAL = Path("C:/Windows/Fonts/arial.ttf")
_ARIAL_BOLD = Path("C:/Windows/Fonts/arialbd.ttf")
if _ARIAL.exists():
    pdfmetrics.registerFont(TTFont("Arial", str(_ARIAL)))
    pdfmetrics.registerFont(TTFont("Arial-Bold", str(_ARIAL_BOLD)))
    UNICODE_FONT = "Arial"
    UNICODE_FONT_BOLD = "Arial-Bold"
else:
    UNICODE_FONT = "Helvetica"
    UNICODE_FONT_BOLD = "Helvetica-Bold"

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = ROOT / "WC2026_Youth_Training_Report.pdf"

ACCENT = colors.HexColor("#C9A52A")       # WC2026 trophy gold
LIGHT_ROW = colors.HexColor("#FDFAED")   # warm cream zebra rows
HEADER_BG = colors.HexColor("#1a3a5c")   # dark navy
HEADER_FG = colors.white
RULE = colors.HexColor("#D4C47A")         # muted gold grid lines
BODY_TEXT = colors.HexColor("#111827")
MUTED = colors.HexColor("#6b7280")

TEAM_TO_COUNTRY = {
    "Algeria": "Algeria", "Argentina": "Argentina", "Australia": "Australia",
    "Austria": "Austria", "Belgium": "Belgium",
    "Bosnia and Herzegovina": "Bosnia and Herzegovina",
    "Brazil": "Brazil", "Canada": "Canada", "Cabo Verde": "Cabo Verde",
    "Colombia": "Colombia", "Croatia": "Croatia", "Curaçao": "Curaçao",
    "Czechia": "Czechia", "DR Congo": "DR Congo", "Ecuador": "Ecuador",
    "Egypt": "Egypt", "England": "England", "France": "France",
    "Germany": "Germany", "Ghana": "Ghana", "Haiti": "Haiti",
    "IR Iran": "Iran", "Iraq": "Iraq", "Côte d'Ivoire": "Côte d'Ivoire",
    "Japan": "Japan", "Jordan": "Jordan", "Korea Republic": "South Korea",
    "Mexico": "Mexico", "Morocco": "Morocco", "Netherlands": "Netherlands",
    "New Zealand": "New Zealand", "Norway": "Norway", "Panama": "Panama",
    "Paraguay": "Paraguay", "Portugal": "Portugal", "Qatar": "Qatar",
    "Saudi Arabia": "Saudi Arabia", "Scotland": "Scotland", "Senegal": "Senegal",
    "South Africa": "South Africa", "Spain": "Spain", "Sweden": "Sweden",
    "Switzerland": "Switzerland", "Tunisia": "Tunisia", "Türkiye": "Türkiye",
    "Uruguay": "Uruguay", "USA": "United States", "Uzbekistan": "Uzbekistan",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def norm(name: str) -> str:
    """Normalize a name to ASCII for fuzzy matching across encoding variants."""
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower().strip()

def open_csv(path):
    """Open a CSV trying UTF-8-BOM first, falling back to latin-1."""
    try:
        f = path.open(encoding="utf-8-sig")
        f.read(1024)
        f.seek(0)
        return f
    except UnicodeDecodeError:
        return path.open(encoding="latin-1")


# ── data loading ──────────────────────────────────────────────────────────────

def compute_coverage(rows: list) -> dict:
    lineups = list(csv.DictReader(open_csv(DATA / "world_cup_match_lineups.csv")))

    unique_matches = len({r["match_id"] for r in lineups})
    unique_starters = {(r["player_name"], r["team_name"]) for r in lineups}

    dates = sorted(r["match_date"] for r in lineups if r.get("match_date"))
    latest_date_raw = dates[-1] if dates else ""
    try:
        dt = datetime.strptime(latest_date_raw, "%Y-%m-%d")
        latest_date = f"{dt.strftime('%B')} {dt.day}, {dt.year}"
    except (ValueError, TypeError):
        latest_date = latest_date_raw

    players_with_years = {
        (r["player_name"], r["national_team"])
        for r in rows
        if r.get("start_age_est", "").strip() and r.get("end_age_est", "").strip()
    }
    players_fallback = {
        (r["player_name"], r["national_team"])
        for r in rows
        if not r.get("start_age_est", "").strip() or not r.get("end_age_est", "").strip()
    }

    training_norm = {(norm(r["player_name"]), r["national_team"]) for r in rows}
    unresolved = sum(
        1 for (name, team) in unique_starters
        if (norm(name), team) not in training_norm
    )

    player_club_counts = collections.Counter(
        (r["player_name"], r["national_team"])
        for r in rows
        if r.get("start_age_est", "").strip() and r.get("end_age_est", "").strip()
    )
    player_countries: dict = collections.defaultdict(set)
    for r in rows:
        if r.get("club_country", "").strip():
            player_countries[(r["player_name"], r["national_team"])].add(r["club_country"].strip())

    return {
        "matches": unique_matches,
        "latest_date": latest_date,
        "starters": len(unique_starters),
        "with_years": len(players_with_years),
        "fallback": len(players_fallback),
        "unresolved": unresolved,
        "club_rows": len(rows),
        "with_country": sum(1 for r in rows if r.get("club_country", "").strip()),
        "multi_club": sum(1 for c in player_club_counts.values() if c > 1),
        "multi_country": sum(1 for cs in player_countries.values() if len(cs) > 1),
    }


def load_data():
    rows = list(csv.DictReader(open_csv(DATA / "player_youth_training.csv")))

    per = collections.defaultdict(list)
    for r in rows:
        per[(r["player_name"], r["national_team"])].append(r)

    countries: dict[str, dict] = collections.defaultdict(
        lambda: {"players": set(), "player_equiv": 0.0}
    )
    clubs: dict[str, dict] = collections.defaultdict(
        lambda: {"players": set(), "player_equiv": 0.0, "country": ""}
    )
    team_stats: dict[str, dict] = collections.defaultdict(
        lambda: {"total_unique": set(), "local_unique": set(), "local_weighted": 0.0}
    )

    for key, recs in per.items():
        player, team = key
        home = TEAM_TO_COUNTRY.get(team, "")
        known = [
            r for r in recs
            if (r["start_age_est"] or "").strip() and (r["end_age_est"] or "").strip()
        ]
        fallback = [
            r for r in recs
            if not (r["start_age_est"] or "").strip() or not (r["end_age_est"] or "").strip()
        ]

        team_stats[team]["total_unique"].add(player)

        if known:
            durs = [
                max(0, int(r["end_age_est"]) - int(r["start_age_est"]))
                for r in known
            ]
            total = sum(durs)
            for r, d in zip(known, durs):
                share = d / total if total else 0
                clubs[r["club_name"]]["players"].add(player)
                clubs[r["club_name"]]["player_equiv"] += share
                if not clubs[r["club_name"]]["country"] and r["club_country"].strip():
                    clubs[r["club_name"]]["country"] = r["club_country"].strip()
                if r["club_country"].strip():
                    countries[r["club_country"]]["players"].add(player)
                    countries[r["club_country"]]["player_equiv"] += share

            local_years = sum(
                d for r, d in zip(known, durs)
                if r["club_country"].strip() == home
            )
            foreign_years = total - local_years
            local_share = local_years / total if total else 0
            team_stats[team]["local_weighted"] += local_share
            if foreign_years < 5:
                team_stats[team]["local_unique"].add(player)
        elif fallback:
            r = fallback[0]
            clubs[r["club_name"]]["players"].add(player)
            if not clubs[r["club_name"]]["country"] and r["club_country"].strip():
                clubs[r["club_name"]]["country"] = r["club_country"].strip()
            if r["club_country"].strip():
                countries[r["club_country"]]["players"].add(player)
            # classify local/foreign based on the single club's country
            if r["club_country"].strip() == home:
                team_stats[team]["local_unique"].add(player)
            elif r["club_country"].strip():
                pass  # foreign club — not locally trained

    def top(d, n=20, by_country=False):
        arr = [
            {
                "name": k,
                "country": v.get("country", ""),
                "unique": len(v["players"]),
                "weighted": round(v["player_equiv"], 2),
            }
            for k, v in d.items()
        ]
        arr.sort(key=lambda x: (-x["unique"], -x["weighted"], x["name"]))
        return arr[:n]

    local_ratios = []
    for team, s in team_stats.items():
        total = len(s["total_unique"])
        local = len(s["local_unique"])
        pct = round(100 * local / total) if total else 0
        local_ratios.append({
            "team": team,
            "total": total,
            "local": local,
            "pct": pct,
        })
    local_ratios.sort(key=lambda x: (-x["pct"], x["team"]))

    coverage = compute_coverage(rows)
    coverage["unique_countries"] = len(countries)
    coverage["unique_clubs"] = len(clubs)

    lineups = list(csv.DictReader(open_csv(DATA / "world_cup_match_lineups.csv")))
    unique_starters = {(r["player_name"], r["team_name"]) for r in lineups}
    training_norm = {(norm(r["player_name"]), r["national_team"]) for r in rows}
    unresolved_list = sorted(
        [(name, team) for (name, team) in unique_starters if (norm(name), team) not in training_norm],
        key=lambda x: (x[1], x[0]),
    )

    return top(countries), top(clubs), local_ratios, coverage, unresolved_list


# ── styles ────────────────────────────────────────────────────────────────────

def make_styles():
    base = getSampleStyleSheet()
    s = {}
    s["title"] = ParagraphStyle(
        "ReportTitle", fontSize=22, leading=28, textColor=HEADER_BG,
        fontName="Helvetica-Bold", alignment=TA_LEFT, spaceAfter=4,
    )
    s["subtitle"] = ParagraphStyle(
        "Subtitle", fontSize=10, leading=14, textColor=MUTED,
        fontName="Helvetica", alignment=TA_LEFT, spaceAfter=2,
    )
    s["section"] = ParagraphStyle(
        "Section", fontSize=13, leading=17, textColor=BODY_TEXT,
        fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=6,
    )
    s["subsection"] = ParagraphStyle(
        "Subsection", fontSize=10, leading=14, textColor=BODY_TEXT,
        fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=4,
    )
    s["body"] = ParagraphStyle(
        "Body", fontSize=9, leading=13, textColor=BODY_TEXT,
        fontName="Helvetica", spaceAfter=4,
    )
    s["caption"] = ParagraphStyle(
        "Caption", fontSize=7.5, leading=10, textColor=MUTED,
        fontName="Helvetica-Oblique", spaceAfter=8,
    )
    s["appendix_title"] = ParagraphStyle(
        "AppTitle", fontSize=15, leading=20, textColor=ACCENT,
        fontName="Helvetica-Bold", spaceBefore=0, spaceAfter=8,
    )
    s["bullet"] = ParagraphStyle(
        "Bullet", fontSize=9, leading=13, textColor=BODY_TEXT,
        fontName="Helvetica", leftIndent=12, spaceAfter=3,
    )
    return s


def table_style(col_count, zebra=True):
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_ROW] if zebra else [colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.3, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    return TableStyle(cmds)


def right_align_cols(t_style, col_indices):
    for ci in col_indices:
        t_style.add("ALIGNMENT", (ci, 0), (ci, -1), "RIGHT")
    return t_style


# ── page templates ────────────────────────────────────────────────────────────

def build_doc(filename):
    W, H = A4
    margin = 2 * cm

    def header_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(margin, 1.2 * cm, "WC 2026 Youth Training Report")
        canvas.drawRightString(W - margin, 1.2 * cm, f"Page {doc.page}")
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.3)
        canvas.line(margin, 1.5 * cm, W - margin, 1.5 * cm)
        canvas.restoreState()

    doc = BaseDocTemplate(
        str(filename),
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
    )
    frame = Frame(margin, 2.5 * cm, W - 2 * margin, H - 5 * cm, id="main")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=header_footer)])
    return doc


# ── content ───────────────────────────────────────────────────────────────────

def build_story(s, top_countries, top_clubs, local_ratios, cov, unresolved_list):
    story = []
    W = A4[0] - 4 * cm  # usable width

    # ── cover ──
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph("WC 2026 Youth Training Report", s["title"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=HEADER_BG, spaceAfter=4))
    story.append(Paragraph(
        "Where the starting-lineup players train between ages 5 and 16?",
        s["subtitle"],
    ))
    story.append(Paragraph(f"Data through {cov['matches']} completed matches · {cov['latest_date']}", s["caption"]))
    story.append(Spacer(1, 0.2 * cm))

    # coverage strip
    cov_data = [
        ["Completed matches", "Unique starters", "Unique training countries", "Unique training clubs"],
        [str(cov["matches"]), str(cov["starters"]),
         str(cov["unique_countries"]), str(cov["unique_clubs"])],
    ]
    cov_t = Table(cov_data, colWidths=[W / 4] * 4, hAlign="LEFT")
    cov_ts = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F5ECC8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), HEADER_BG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, 1), 14),
        ("TEXTCOLOR", (0, 1), (-1, 1), ACCENT),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.3, RULE),
    ])
    cov_t.setStyle(cov_ts)
    story.append(cov_t)
    story.append(Spacer(1, 0.4 * cm))

    # ── top countries ──
    story.append(Paragraph("Top 20 Training Countries", s["section"]))
    story.append(Paragraph(
        "<b>Unique starters</b> counts each player once for every country where they trained, "
        "regardless of how long they spent there.",
        s["body"],
    ))
    story.append(Paragraph(
        "<b>Weighted starters</b> allocates each player as a fraction across countries in proportion "
        "to the years they spent training there between ages 5 and 16 — for example, a player who "
        "trained 8 years in France and 4 years in Spain contributes 0.67 to France and 0.33 to Spain. "
        "See Appendix 1 for the full counting rule.",
        s["body"],
    ))

    hdr = ["#", "Country", "Unique starters", "Weighted starters"]
    c_data = [hdr] + [
        [str(i + 1), r["name"], str(r["unique"]), f"{r['weighted']:.2f}"]
        for i, r in enumerate(top_countries)
    ]
    cw = [0.9 * cm, 5.8 * cm, 3 * cm, 3.3 * cm]
    ct = Table(c_data, colWidths=cw, hAlign="LEFT")
    ts = table_style(4)
    right_align_cols(ts, [2, 3])
    ct.setStyle(ts)
    story.append(ct)

    # ── top clubs ──
    story.append(PageBreak())
    story.append(Paragraph("Top 20 Training Clubs", s["section"]))
    story.append(Paragraph(
        "Same year-share method as above, applied at club level. Players who moved between clubs "
        "are split across each club in proportion to time spent there.",
        s["body"],
    ))

    hdr2 = ["#", "Club", "Country", "Unique starters", "Weighted starters"]
    cl_data = [hdr2] + [
        [str(i + 1), r["name"], r["country"], str(r["unique"]), f"{r['weighted']:.2f}"]
        for i, r in enumerate(top_clubs)
    ]
    cw2 = [0.9 * cm, 4.8 * cm, 3 * cm, 2.7 * cm, 2.7 * cm]
    clt = Table(cl_data, colWidths=cw2, hAlign="LEFT")
    ts2 = table_style(5)
    right_align_cols(ts2, [3, 4])
    clt.setStyle(ts2)
    story.append(clt)

    # ── local-trained ratio (page 3) ──
    story.append(PageBreak())
    story.append(Paragraph("Local-Trained Ratio by National Team", s["section"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=RULE, spaceAfter=8))
    story.append(Paragraph(
        "Percentage of each team's tracked starters classified as locally trained. A player is "
        "locally trained if they have fewer than 5 foreign-country years on record. For players "
        "with no year data, classification is based solely on their club's country. "
        "Sorted from highest to lowest.",
        s["body"],
    ))
    story.append(Spacer(1, 0.2 * cm))

    a2_hdr = ["National team", "Tracked starters", "Locally trained", "Local ratio"]
    a2_data = [a2_hdr] + [
        [r["team"], str(r["total"]), str(r["local"]), f"{r['pct']}%"]
        for r in local_ratios
    ]
    aw = [5 * cm, 3 * cm, 3 * cm, 3 * cm]
    a2t = Table(a2_data, colWidths=aw, hAlign="LEFT")
    ts3 = table_style(4)
    right_align_cols(ts3, [1, 2, 3])
    for i, r in enumerate(local_ratios, start=1):
        if r["pct"] == 100:
            ts3.add("TEXTCOLOR", (3, i), (3, i), colors.HexColor("#166534"))
            ts3.add("FONTNAME", (3, i), (3, i), "Helvetica-Bold")
    a2t.setStyle(ts3)
    story.append(a2t)

    # ── Appendix 1 ──
    story.append(PageBreak())
    story.append(Paragraph("Appendix 1 — Data Conditions and Counting Rules", s["appendix_title"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=RULE, spaceAfter=8))

    story.append(Paragraph("Data sources", s["subsection"]))
    for line in [
        "<b>Starting XIs</b>: Wikipedia 2026 FIFA World Cup group and knockout-stage pages, "
        "scraped via BeautifulSoup. Each starting-XI row is linked to its match section URL.",
        "<b>Youth-club histories</b>: Wikipedia player infobox 'Youth career' section, "
        "fetched per player. Year spans and club names are parsed directly from the infobox table.",
        "<b>Club countries</b>: Inferred from each linked club's Wikipedia page lead text and "
        "categories using phrase-pattern matching.",
    ]:
        story.append(Paragraph(f"• {line}", s["bullet"]))
    story.append(Spacer(1, 0.2 * cm))

    story.append(Paragraph("Age window", s["subsection"]))
    story.append(Paragraph(
        "Only training that overlaps the age range 5–16 is included. If a Wikipedia source gives "
        "a spell of 2008–2015 for a player born in 2000, that is converted to ages 8–15 and "
        "clipped to the 5–16 window.",
        s["body"],
    ))

    story.append(Paragraph("Counting rule for players who moved", s["subsection"]))
    story.append(Paragraph(
        "Each player's contribution is split across clubs and countries in proportion to the number "
        "of years they spent at each during ages 5–16. For example, a player who trained 8 years "
        "in France and 4 years in Spain contributes 0.67 to France and 0.33 to Spain. "
        "Where no year data is available, an equal split across clubs is used as a fallback.",
        s["body"],
    ))
    story.append(Spacer(1, 0.2 * cm))

    story.append(Paragraph("Confidence tiers", s["subsection"]))
    for line in [
        "<b>Medium</b>: year span extracted from Wikipedia infobox; age estimates calculated "
        "from the player's birth year.",
        "<b>Low (fallback)</b>: only a club name was available with no year span. The club is "
        "counted in unique starters but contributes 0 to weighted starters.",
        f"<b>Unresolved</b>: {cov['unresolved']} players have no usable youth section on Wikipedia. They are "
        "excluded from all rankings.",
    ]:
        story.append(Paragraph(f"• {line}", s["bullet"]))
    story.append(Spacer(1, 0.2 * cm))

    story.append(Paragraph("Known limitations", s["subsection"]))
    for line in [
        f"The tournament was still in progress on the data collection date (2026-07-05). "
        f"Knockout matches from the Round of 16 onwards are partially included.",
        "Club-country assignment is automated and may misclassify youth academies with ambiguous "
        "Wikipedia pages.",
        f"Multi-country starters ({cov['multi_country']}) are split across countries; "
        f"multi-club starters ({cov['multi_club']}) are split across clubs.",
        f"Country backfill covers {cov['with_country']} of {cov['club_rows']} youth-club rows. "
        f"Rows without a country are excluded from country rankings only.",
    ]:
        story.append(Paragraph(f"• {line}", s["bullet"]))
    story.append(Spacer(1, 0.2 * cm))

    story.append(Paragraph("Players with no training data", s["subsection"]))
    story.append(Paragraph(
        f"The following {len(unresolved_list)} starters have no rows in the youth training table "
        "and are excluded from all rankings. Youth history still needs to be researched for these players.",
        s["body"],
    ))
    story.append(Spacer(1, 0.15 * cm))
    ur_hdr = ["Player", "National team"]
    ur_data = [ur_hdr] + [[name, team] for name, team in unresolved_list]
    ur_cw = [8 * cm, 5 * cm]
    ur_t = Table(ur_data, colWidths=ur_cw, hAlign="LEFT")
    ur_ts = table_style(2)
    ur_ts.add("FONTNAME", (0, 1), (-1, -1), UNICODE_FONT)
    ur_t.setStyle(ur_ts)
    story.append(ur_t)
    story.append(Spacer(1, 0.2 * cm))

    story.append(Paragraph("Source data", s["subsection"]))
    story.append(Paragraph(
        "Collected data for this report can be found at: "
        "<a href=\"https://github.com/lorihe/WC2026-youth-clubs/tree/main/data\" color=\"#1a3a5c\">"
        "github.com/lorihe/WC2026-youth-clubs/tree/main/data</a>",
        s["body"],
    ))
    story.append(Paragraph(
        f"900+ youth clubs weren't easy to trace. "
        " If you spot an error or have a better source, comments "
        "are genuinely appreciated.",
        s["body"],
    ))

    return story


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("Loading data...")
    top_countries, top_clubs, local_ratios, cov, unresolved_list = load_data()

    print("Building PDF...")
    s = make_styles()
    doc = build_doc(OUTPUT)
    story = build_story(s, top_countries, top_clubs, local_ratios, cov, unresolved_list)
    doc.build(story)
    print(f"Saved: {OUTPUT}")


if __name__ == "__main__":
    main()
