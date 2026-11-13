#!/usr/bin/env python3
"""Redraws the contribution graph and the plain-text stats block in README.md.

Standard library only: the GitHub Action that runs this needs no dependencies.

    GH_TOKEN=$(gh auth token) python scripts/generate.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import urllib.request

USER = os.environ.get("GH_PROFILE_USER", "HyawiiGithub")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""

API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
DOCS = os.path.join(ROOT, "docs")
README = os.path.join(ROOT, "README.md")

# palette taken from vanguard-group/styles.css so this matches the rest of the projects
CARD = "#0d1633"
EDGE = "#1e2750"
MUTED = "#9aa3c7"
GOLD = "#d4a94e"
LEVELS = ["#212c66", "#4a1220", "#8f0d22", "#C4122E", "#e8b04b"]

FONT = "Inter, ui-sans-serif, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"


# --------------------------------------------------------------------------- http


def _request(url: str, payload: dict | None = None) -> str:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": f"{USER}-graph"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", "replace")


def get_json(url: str):
    return json.loads(_request(url))


# ----------------------------------------------------------------------- fetching

CALENDAR_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount contributionLevel } }
      }
    }
  }
}
"""

LEVEL_MAP = {
    "NONE": 0,
    "FIRST_QUARTILE": 1,
    "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3,
    "FOURTH_QUARTILE": 4,
}


def fetch_calendar() -> list[tuple[dt.date, int, int]]:
    today = dt.date.today()
    start = today - dt.timedelta(days=364)

    if TOKEN:
        try:
            res = json.loads(
                _request(
                    GRAPHQL,
                    {
                        "query": CALENDAR_QUERY,
                        "variables": {
                            "login": USER,
                            "from": start.isoformat() + "T00:00:00Z",
                            "to": today.isoformat() + "T23:59:59Z",
                        },
                    },
                )
            )
            weeks = (
                ((res.get("data") or {}).get("user") or {})
                .get("contributionsCollection", {})
                .get("contributionCalendar", {})
                .get("weeks", [])
            )
            days = [
                (
                    dt.date.fromisoformat(d["date"]),
                    int(d.get("contributionCount", 0)),
                    LEVEL_MAP.get(d.get("contributionLevel", "NONE"), 0),
                )
                for week in weeks
                for d in week.get("contributionDays", [])
            ]
            if days:
                return sorted(days)
            print("  graphql gave no days, scraping instead")
        except Exception as err:  # noqa: BLE001 - fall through to the public page
            print(f"  graphql failed ({err}), scraping instead")

    html = _request(f"https://github.com/users/{USER}/contributions")

    # counts live in the tooltips, keyed by day component id
    by_id: dict[str, int] = {}
    for cell, text in re.findall(r'<tool-tip[^>]*for="(contribution-day-component-[\d-]+)"[^>]*>([^<]*)</tool-tip>', html):
        digits = re.search(r"(\d+)", text)
        by_id[cell] = int(digits.group(1)) if digits else 0

    days = []
    for tag in re.findall(r"<td\b[^>]*>", html):
        date = re.search(r'data-date="(\d{4}-\d{2}-\d{2})"', tag)
        if not date:
            continue
        level = re.search(r'data-level="(\d)"', tag)
        cell = re.search(r'id="(contribution-day-component-[\d-]+)"', tag)
        count = by_id.get(cell.group(1), 0) if cell else 0
        days.append(
            (
                dt.date.fromisoformat(date.group(1)),
                count,
                int(level.group(1)) if level else (1 if count else 0),
            )
        )
    if not days:
        raise SystemExit("could not read the contribution calendar")
    return sorted(days)


def fetch_languages() -> list[tuple[str, float]]:
    totals: dict[str, int] = {}
    repos = get_json(f"{API}/users/{USER}/repos?per_page=100&type=owner&sort=pushed")
    for repo in repos[:45]:
        if repo.get("fork"):
            continue
        try:
            for name, size in get_json(f"{API}/repos/{USER}/{repo['name']}/languages").items():
                totals[name] = totals.get(name, 0) + int(size)
        except Exception:  # noqa: BLE001 - empty repos come back 404
            continue
    total = sum(totals.values())
    if not total:
        return []
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return [(name, size / total * 100.0) for name, size in ranked]


# ---------------------------------------------------------------------- analytics


def week_starts(days: list[tuple[dt.date, int, int]]) -> list[dt.date]:
    starts = set()
    for date, _c, _l in days:
        starts.add(date - dt.timedelta(days=(date.weekday() + 1) % 7))
    return sorted(starts)


def streaks(days: list[tuple[dt.date, int, int]]) -> tuple[int, int]:
    counts = {d: c for d, c, _l in days}
    ordered = sorted(counts)

    longest = run = 0
    previous = None
    for date in ordered:
        if counts[date] <= 0:
            run, previous = 0, date
            continue
        joined = previous is not None and (date - previous).days == 1 and counts.get(previous, 0) > 0
        run = run + 1 if joined else 1
        previous = date
        longest = max(longest, run)

    today = dt.date.today()
    cursor = today if counts.get(today, 0) > 0 else today - dt.timedelta(days=1)
    current = 0
    while counts.get(cursor, 0) > 0:
        current += 1
        cursor -= dt.timedelta(days=1)
    return current, longest


# ------------------------------------------------------------------------- drawing


def levels(days: list[tuple[dt.date, int, int]]) -> dict[dt.date, int]:
    """Bucket days against this account's own spread so the grid keeps contrast."""
    values = sorted(c for _d, c, _l in days if c > 0)
    if not values:
        return {d: 0 for d, _c, _l in days}

    def cut(p: float) -> float:
        return values[min(len(values) - 1, max(0, round(p * (len(values) - 1))))]

    q1, q2, q3 = cut(0.25), cut(0.5), cut(0.75)
    out = {}
    for date, count, _level in days:
        if count <= 0:
            out[date] = 0
        elif count <= q1:
            out[date] = 1
        elif count <= q2:
            out[date] = 2
        elif count <= q3:
            out[date] = 3
        else:
            out[date] = 4
    return out


def render_graph(days: list[tuple[dt.date, int, int]]) -> str:
    """Just the grid: no panel, no title, no glow, transparent background."""
    weeks = week_starts(days)
    shade = levels(days)
    counts = {d: c for d, c, _l in days}
    total = sum(counts.values())

    cell, step = 11, 15
    width = 840
    left, top = 36, 84
    grid_h = 7 * step - (step - cell)
    height = top + grid_h + 24

    # cells are drawn as-is: no resting state of opacity 0, so the grid still reads
    # if the image is cached, throttled or rendered without animations. today's cell
    # gets a pulse on top, which only ever adds.
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="contribution graph for the last year">',
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="16" '
        f'fill="{CARD}" stroke="{EDGE}"/>',
        f'<text x="26" y="34" font-family="{MONO}" font-size="9.5" letter-spacing="2.2" '
        f'fill="{MUTED}">CONTRIBUTIONS \u00b7 LAST 12 MONTHS</text>',
        f'<text x="{width - 26}" y="34" text-anchor="end" font-family="{MONO}" '
        f'font-size="12" font-weight="700" fill="{GOLD}">{total:,} this year</text>',
    ]

    previous_month = None
    for index, week in enumerate(weeks):
        if week.month != previous_month and index < len(weeks) - 1:
            out.append(
                f'<text x="{left + index * step}" y="{top - 10}" font-family="{MONO}" '
                f'font-size="9" fill="{MUTED}">{week.strftime("%b").lower()}</text>'
            )
        previous_month = week.month

    for row, label in ((1, "mon"), (3, "wed"), (5, "fri")):
        out.append(
            f'<text x="{left - 10}" y="{top + row * step + 9}" font-family="{MONO}" '
            f'font-size="9" text-anchor="end" fill="{MUTED}">{label}</text>'
        )

    for index, week in enumerate(weeks):
        for row in range(7):
            date = week + dt.timedelta(days=row)
            if date not in counts:
                continue
            count = counts[date]
            out.append(
                f'<rect x="{left + index * step}" y="{top + row * step}" width="{cell}" '
                f'height="{cell}" rx="2" fill="{LEVELS[shade.get(date, 0)]}">'
                f"<title>{date.isoformat()}: {count}</title></rect>"
            )

    today = dt.date.today()
    if today in counts:
        week = today - dt.timedelta(days=(today.weekday() + 1) % 7)
        if week in weeks:
            x = left + weeks.index(week) * step
            y = top + (today.weekday() + 1) % 7 * step
            out.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" '
                f'fill="none" stroke="{GOLD}" stroke-width="1.4">'
                '<animate attributeName="stroke-opacity" values="1;0.25;1" dur="3s" '
                'repeatCount="indefinite"/></rect>'
            )

    out.append("</svg>")
    return "".join(out)






def stats_block(days: list[tuple[dt.date, int, int]], languages: list[tuple[str, float]]) -> str:
    total = sum(c for _d, c, _l in days)
    active = sum(1 for _d, c, _l in days if c > 0)
    current, longest = streaks(days)

    by_date = {d: c for d, c, _l in days}
    today = dt.date.today()
    recent = sum(by_date.get(today - dt.timedelta(days=i), 0) for i in range(30))
    peak_date, peak = max(((d, c) for d, c, _l in days), key=lambda pair: pair[1])

    lines = ["```text"]
    lines.append(
        f"{total:,} contributions  |  {active} active days  |  {current} day streak "
        f"(best {longest})"
    )
    lines.append(
        f"last 30 days  {recent:,}  |  busiest day  {peak:,} "
        f"({peak_date.strftime('%b').lower()} {peak_date.day})"
    )
    if languages:
        lines.append("")
        lines.append(
            "   ".join(f"{name.lower()} {pct:.0f}%" for name, pct in languages[:5])
        )
    lines.append("```")
    return "\n".join(lines)


def write_readme(block: str) -> bool:
    with open(README, encoding="utf-8") as fh:
        text = fh.read()
    pattern = re.compile(r"(<!-- stats:start -->\n)(.*?)(<!-- stats:end -->)", re.S)
    if not pattern.search(text):
        print("  README markers missing, skipped")
        return False
    updated = pattern.sub(lambda m: m.group(1) + block + "\n" + m.group(3), text)
    if updated == text:
        return False
    with open(README, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(updated)
    return True


def render_play_button() -> str:
    width, height = 240, 44
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="play the market game">'
        '<defs><linearGradient id="btn" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#e01a3a"/><stop offset="1" stop-color="#C4122E"/>'
        "</linearGradient></defs>"
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="12" '
        f'fill="url(#btn)" stroke="#7d1226"/>'
        f'<path d="M20 15 l11 7 -11 7 z" fill="{GOLD}"/>'
        f'<text x="42" y="27" font-family="{MONO}" font-size="10.5" font-weight="700" '
        'letter-spacing="1.6" fill="#ffffff">PLAY THE MARKET GAME</text>'
        "</svg>"
    )


# ---------------------------------------------------------------------------- main


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.makedirs(ASSETS, exist_ok=True)
    print(f"reading {USER}")

    days = fetch_calendar()
    print(f"  {len(days)} days, {sum(c for _d, c, _l in days):,} contributions")

    try:
        languages = fetch_languages()
    except Exception as err:  # noqa: BLE001 - still worth drawing the graph
        print(f"  language lookup failed ({err})")
        languages = []

    graph = render_graph(days)
    with open(os.path.join(ASSETS, "graph.svg"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(graph)
    print(f"  wrote assets/graph.svg ({len(graph) / 1024:.1f} KB)")

    with open(os.path.join(ASSETS, "play.svg"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_play_button())
    print("  wrote assets/play.svg")

    block = stats_block(days, languages)
    print(f"  README block {'updated' if write_readme(block) else 'unchanged'}")
    print(block)

    current, longest = streaks(days)
    shade = levels(days)
    peak_date, peak = max(((d, c) for d, c, _l in days), key=lambda pair: pair[1])

    # the page in docs/ reads this for the hoverable grid
    os.makedirs(DOCS, exist_ok=True)
    payload = {
        "user": USER,
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": sum(c for _d, c, _l in days),
        "active_days": sum(1 for _d, c, _l in days if c > 0),
        "current_streak": current,
        "longest_streak": longest,
        "busiest": {"date": peak_date.isoformat(), "count": peak},
        "languages": [{"name": n, "percent": round(p, 1)} for n, p in languages[:5]],
        "days": [[d.isoformat(), c, shade[d]] for d, c, _l in days],
    }
    with open(os.path.join(DOCS, "data.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    print("  wrote docs/data.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
