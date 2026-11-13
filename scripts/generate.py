#!/usr/bin/env python3
"""Redraws the contribution graph and the plain-text stats block in README.md.

Standard library only: the GitHub Action that runs this needs no dependencies.

    GH_TOKEN=$(gh auth token) python scripts/generate.py
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import random
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

# crown keeps its base tokens in src/web/styles.css, so the cards use the same ones
BG = "#09090b"
CARD = "#131318"
EDGE = "#232329"
INK = "#ededf0"
MUTED = "#8b8b96"
ACCENT = "#a78bfa"
POSITIVE = "#4ade80"
NEGATIVE = "#f87171"
LEVELS = ["#1b1b22", "#2a2350", "#43348c", "#7c5cf5", "#c9b8ff"]

FONT = "Inter, 'Segoe UI', system-ui, -apple-system, Helvetica, Arial, sans-serif"
DISPLAY = "'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "'SF Mono', Menlo, Consolas, ui-monospace, monospace"


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
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="6" '
        f'fill="{CARD}" stroke="{EDGE}"/>',
        f'<text x="26" y="34" font-family="{MONO}" font-size="9.5" letter-spacing="2.2" '
        f'fill="{MUTED}">CONTRIBUTIONS / LAST 12 MONTHS</text>',
        f'<text x="{width - 26}" y="34" text-anchor="end" font-family="{MONO}" '
        f'font-size="12" font-weight="700" fill="{ACCENT}">{total:,} this year</text>',
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
                f'fill="none" stroke="{ACCENT}" stroke-width="1.4">'
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


def smooth_path(points: list[tuple[float, float]]) -> str:
    if not points:
        return ""
    out = [f"M {points[0][0]:.2f} {points[0][1]:.2f}"]
    total = len(points)
    for index in range(total - 1):
        p0 = points[index - 1] if index > 0 else points[index]
        p1, p2 = points[index], points[index + 1]
        p3 = points[index + 2] if index + 2 < total else points[index + 1]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0)
        out.append(
            f" C {c1[0]:.2f} {c1[1]:.2f}, {c2[0]:.2f} {c2[1]:.2f}, {p2[0]:.2f} {p2[1]:.2f}"
        )
    return "".join(out)


def compact_money(amount: float) -> str:
    for size, suffix in ((10 ** 12, "T"), (10 ** 9, "B"), (10 ** 6, "M"), (10 ** 3, "K")):
        if amount >= size:
            return f"${amount / size:,.2f}{suffix}"
    return f"${amount:,.0f}"


HISTORY_START = dt.date(2020, 1, 1)
PATH_SEED = 20200101
PER_COMMIT = 5_137  # keeps the total in the low hundreds of millions
WORTH_CEILING = 299_400_000.0


def worth_history(end_date: dt.date, end_value: float) -> list[tuple[dt.date, float]]:
    """Seeded daily market series since 2020 that lands exactly on end_value."""
    if end_date <= HISTORY_START or end_value <= 0:
        return [(end_date, max(end_value, 0.0))]

    sessions = (end_date - HISTORY_START).days + 1
    rng = random.Random(PATH_SEED)
    opening = rng.uniform(88_000_000, 104_000_000)
    log_open, log_end = math.log(opening), math.log(end_value)

    # a mean reverting wobble around the trend, so it stays volatile instead of
    # wandering off into the trillions over six years
    wobble = [0.0]
    level = 0.0
    for _ in range(1, sessions):
        level = level * 0.995 + rng.gauss(0.0, 0.022)
        if rng.random() < 0.008:
            level += rng.choice((-1.0, 1.0)) * rng.uniform(0.05, 0.12)
        wobble.append(level)

    tail = wobble[-1]
    out = []
    for index in range(sessions):
        progress = index / (sessions - 1)
        trend = math.exp(log_open + (log_end - log_open) * progress)
        # swings get scaled to the room left under the ceiling, so the cap compresses
        # the moves near the top instead of slicing a flat lid across the line
        headroom = math.log(WORTH_CEILING / trend)
        limit = max(0.02, min(headroom * 0.9, 0.55))
        curve = math.log(trend) + limit * math.tanh((wobble[index] - tail * progress) / limit)
        out.append((HISTORY_START + dt.timedelta(days=index), math.exp(curve)))
    return out


def render_worth(days: list[tuple[dt.date, int, int]]) -> str:
    """Market history since 2020 that finishes on the commit derived number."""
    total = sum(count for _d, count, _l in days)
    worth = total * PER_COMMIT
    today = days[-1][0] if days else dt.date.today()
    history = worth_history(today, worth)
    previous = history[-2][1] if len(history) > 1 else worth
    change = (worth - previous) / previous * 100 if previous else 0.0
    best_day = max((count for _d, count, _l in days), default=0) * PER_COMMIT

    width, height = 840, 292
    x0, x1 = 78, 814
    y0, y1 = 128, 250

    values = [value for _date, value in history]
    lo, hi = min(values), max(values)
    lo_log, hi_log = math.log(lo), math.log(hi)
    spread = (hi_log - lo_log) or 1.0

    def px(index: int) -> float:
        return x0 + (x1 - x0) * index / max(1, len(history) - 1)

    def py(value: float) -> float:
        return y1 - (math.log(value) - lo_log) / spread * (y1 - y0)

    sampled = list(range(0, len(history), 2))
    if sampled[-1] != len(history) - 1:
        sampled.append(len(history) - 1)
    parts = [f"M {px(sampled[0]):.1f} {py(history[sampled[0]][1]):.1f}"]
    parts += [f" L {px(i):.1f} {py(history[i][1]):.1f}" for i in sampled[1:]]
    line = "".join(parts)
    area = line + f" L {x1:.1f} {y1} L {x0:.1f} {y1} Z"
    last_x, last_y = px(len(history) - 1), py(worth)

    grid = []
    for exponent in range(int(math.floor(math.log10(lo))), int(math.ceil(math.log10(hi))) + 1):
        for step in (1, 2, 5):
            level = (10 ** exponent) * step
            if not (lo <= level <= hi):
                continue
            gy = py(level)
            grid.append(
                f'<line x1="{x0}" y1="{gy:.1f}" x2="{x1}" y2="{gy:.1f}" stroke="{EDGE}" '
                'stroke-dasharray="2 4"/>'
                f'<text x="30" y="{gy + 3:.1f}" font-family="{MONO}" font-size="8" '
                f'fill="{MUTED}">{compact_money(level)}</text>'
            )

    ticks = []
    for year in range(HISTORY_START.year, today.year + 1):
        mark = dt.date(year, 1, 1)
        if not (HISTORY_START <= mark <= today):
            continue
        gx = px((mark - HISTORY_START).days)
        ticks.append(
            f'<line x1="{gx:.1f}" y1="{y0}" x2="{gx:.1f}" y2="{y1}" stroke="{EDGE}" '
            'stroke-dasharray="2 4"/>'
            f'<text x="{gx:.1f}" y="{y1 + 17}" text-anchor="middle" font-family="{MONO}" '
            f'font-size="8.5" fill="{MUTED}">{year}</text>'
        )

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="net worth over the last year">',
        "<defs>",
        '<linearGradient id="worthfill" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#a78bfa" stop-opacity="0.42"/>'
        '<stop offset="1" stop-color="#a78bfa" stop-opacity="0"/>'
        "</linearGradient>",
        f'<linearGradient id="worthline" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0" stop-color="#6d5bd0"/><stop offset="1" stop-color="{ACCENT}"/>'
        "</linearGradient>",
        "</defs>",
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="6" '
        f'fill="{CARD}" stroke="{EDGE}"/>',
        f'<text x="26" y="38" font-family="{MONO}" font-size="9.5" letter-spacing="2.2" '
        f'fill="{MUTED}">NET WORTH / HYW / USD</text>',
        f'<text x="{width - 26}" y="40" text-anchor="end" font-family="{MONO}" '
        f'font-size="11" font-weight="600" fill="{POSITIVE if change >= 0 else NEGATIVE}">'
        f"{'+' if change >= 0 else ''}{change:.2f}% today</text>",
        f'<text x="26" y="94" font-family="{DISPLAY}" font-size="38" font-weight="700" '
        f'letter-spacing="-1" fill="{INK}">{compact_money(worth)}</text>',
        f'<text x="26" y="114" font-family="{MONO}" font-size="9.5" fill="{MUTED}">'
        f"${worth:,.0f}</text>",
        f'<text x="268" y="114" font-family="{MONO}" font-size="9.5" fill="{MUTED}">'
        f"{total:,} commits</text>",
        f'<text x="432" y="114" font-family="{MONO}" font-size="9.5" fill="{POSITIVE}">'
        f"best day {compact_money(best_day)}</text>",
        *grid,
        *ticks,
        f'<path d="{area}" fill="url(#worthfill)"/>',
        f'<path d="{line}" fill="none" stroke="url(#worthline)" stroke-width="1.6" '
        f'stroke-linejoin="round"/>',
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3.4" fill="{ACCENT}"/>',
        f'<text x="{x0}" y="{height - 8}" font-family="{MONO}" font-size="8.5" '
        f'fill="{MUTED}">since jan 2020 / {len(history):,} sessions</text>',
        "</svg>",
    ]
    return "".join(out)


def render_play_button() -> str:
    width, height = 240, 44
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="play the market game">'
        '<defs><linearGradient id="btn" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#8f74ff"/><stop offset="1" stop-color="#6d5bd0"/>'
        "</linearGradient></defs>"
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="4" '
        f'fill="url(#btn)" stroke="#4b3f8f"/>'
        f'<path d="M20 15 l11 7 -11 7 z" fill="#ffffff"/>'
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

    with open(os.path.join(ASSETS, "worth.svg"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_worth(days))
    print("  wrote assets/worth.svg")

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
    total_commits = sum(c for _d, c, _l in days)
    session_end = days[-1][0] if days else dt.date.today()
    history = worth_history(session_end, total_commits * PER_COMMIT)
    last_change = ((history[-1][1] - history[-2][1]) / history[-2][1] * 100) if len(history) > 1 else 0.0
    payload = {
        "user": USER,
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": total_commits,
        "net_worth": total_commits * PER_COMMIT,
        "per_commit": PER_COMMIT,
        "change_pct": round(last_change, 2),
        "history": {
            "start": history[0][0].isoformat(),
            "values": [round(value) for _date, value in history],
        },
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
