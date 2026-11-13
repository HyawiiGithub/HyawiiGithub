#!/usr/bin/env python3
"""Draws the animated SVG cards that live in assets/ and are embedded in README.md.

Standard library only, so the GitHub Action that refreshes this repo needs no
dependencies. Data comes from the GitHub GraphQL API (falling back to the public
contributions page) plus the REST API for repos/languages.

Run locally:

    GH_TOKEN=$(gh auth token) python scripts/generate.py
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request

USER = os.environ.get("GH_PROFILE_USER", "HyawiiGithub")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""

API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets")

W = 840
FONT = (
    "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
)

INK = "#e8eefb"
MUTED = "#7d8aa3"
PANEL = "#0a0e17"
PANEL_EDGE = "#1a2333"

LEVELS = ["#151d2b", "#12334b", "#12647d", "#22a8c4", "#6df3ff"]

ACCENTS = ["#6df3ff", "#8b9dff", "#c58bff", "#ff8bd0"]

LANG_COLORS = {
    "TypeScript": "#3178c6",
    "JavaScript": "#f1e05a",
    "Python": "#3572A5",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "C#": "#178600",
    "Java": "#b07219",
    "Rust": "#dea584",
    "Go": "#00ADD8",
    "Shell": "#89e051",
    "C++": "#f34b7d",
    "Lua": "#000080",
    "PHP": "#4F5D95",
    "Vue": "#41b883",
    "Svelte": "#ff3e00",
    "Astro": "#ff5a03",
    "MDX": "#fcb32c",
    "EJS": "#a91e50",
    "Dockerfile": "#384d54",
}
FALLBACK_COLORS = ["#6df3ff", "#8b9dff", "#c58bff", "#ff8bd0", "#7ef0b8", "#ffd166"]


# --------------------------------------------------------------------------- http


def _request(url: str, payload: dict | None = None) -> str:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{USER}-profile-cards",
    }
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


def graphql(query: str, variables: dict):
    return json.loads(_request(GRAPHQL, {"query": query, "variables": variables}))


# ----------------------------------------------------------------------- fetching

CALENDAR_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalPullRequestReviewContributions
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
            contributionLevel
          }
        }
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


def fetch_calendar() -> dict:
    """Returns {days: [(date, count, level)], total, commits, prs, issues, reviews}."""
    today = dt.date.today()
    start = today - dt.timedelta(days=364)

    if TOKEN:
        try:
            res = graphql(
                CALENDAR_QUERY,
                {
                    "login": USER,
                    "from": start.isoformat() + "T00:00:00Z",
                    "to": today.isoformat() + "T23:59:59Z",
                },
            )
            coll = (res.get("data") or {}).get("user", {}).get("contributionsCollection") or {}
            cal = coll.get("contributionCalendar") or {}
            days = []
            for week in cal.get("weeks", []):
                for day in week.get("contributionDays", []):
                    days.append(
                        (
                            dt.date.fromisoformat(day["date"]),
                            int(day.get("contributionCount", 0)),
                            LEVEL_MAP.get(day.get("contributionLevel", "NONE"), 0),
                        )
                    )
            if days:
                return {
                    "days": days,
                    "total": int(cal.get("totalContributions", sum(d[1] for d in days))),
                    "commits": int(coll.get("totalCommitContributions", 0)),
                    "prs": int(coll.get("totalPullRequestContributions", 0)),
                    "issues": int(coll.get("totalIssueContributions", 0)),
                    "reviews": int(coll.get("totalPullRequestReviewContributions", 0)),
                }
            print("  graphql returned no days, falling back to html")
        except Exception as err:  # noqa: BLE001 - fall through to the scraper
            print(f"  graphql failed ({err}), falling back to html")

    # Public contributions page: works without a token and in Actions.
    html = _request(f"https://github.com/users/{USER}/contributions")
    days = []
    for tag in re.findall(r"<td\b[^>]*>", html):
        date = re.search(r'data-date="(\d{4}-\d{2}-\d{2})"', tag)
        if not date:
            continue
        count = re.search(r'data-count="(\d+)"', tag)
        level = re.search(r'data-level="(\d)"', tag)
        days.append(
            (
                dt.date.fromisoformat(date.group(1)),
                int(count.group(1)) if count else 0,
                int(level.group(1)) if level else 0,
            )
        )
    if not days:
        raise SystemExit("could not read the contribution calendar")
    days.sort()
    return {
        "days": days,
        "total": sum(d[1] for d in days),
        "commits": None,
        "prs": None,
        "issues": None,
        "reviews": None,
    }


def fetch_repos() -> list[dict]:
    repos, page = [], 1
    while page <= 3:
        batch = get_json(
            f"{API}/users/{USER}/repos?per_page=100&page={page}&sort=pushed&type=owner"
        )
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def fetch_languages(repos: list[dict]) -> list[tuple[str, float]]:
    totals: dict[str, int] = {}
    for repo in repos[:45]:
        if repo.get("fork"):
            continue
        try:
            langs = get_json(f"{API}/repos/{USER}/{repo['name']}/languages")
        except Exception:  # noqa: BLE001 - empty repos 404 sometimes
            continue
        for name, size in langs.items():
            totals[name] = totals.get(name, 0) + int(size)
    total = sum(totals.values())
    if not total:
        return []
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return [(name, size / total * 100.0) for name, size in ranked]


# ---------------------------------------------------------------------- analytics


def week_starts(days: list[tuple[dt.date, int, int]]) -> list[dt.date]:
    starts = {}
    for date, _count, _level in days:
        row = (date.weekday() + 1) % 7  # sunday = row 0
        starts[date - dt.timedelta(days=row)] = True
    return sorted(starts)


def row_of(date: dt.date) -> int:
    return (date.weekday() + 1) % 7


def streaks(days: list[tuple[dt.date, int, int]]) -> tuple[int, int]:
    counts = {d: c for d, c, _l in days}
    ordered = sorted(counts)

    longest = current_run = 0
    previous = None
    for date in ordered:
        if counts[date] <= 0:
            current_run, previous = 0, date
            continue
        joined = previous is not None and (date - previous).days == 1 and counts.get(previous, 0) > 0
        current_run = current_run + 1 if joined else 1
        previous = date
        longest = max(longest, current_run)

    today = dt.date.today()
    cursor = today if counts.get(today, 0) > 0 else today - dt.timedelta(days=1)
    streak = 0
    while counts.get(cursor, 0) > 0:
        streak += 1
        cursor -= dt.timedelta(days=1)
    return streak, longest


def smooth_path(points: list[tuple[float, float]]) -> str:
    if not points:
        return ""
    out = [f"M {points[0][0]:.2f} {points[0][1]:.2f}"]
    n = len(points)
    for i in range(n - 1):
        p0 = points[i - 1] if i > 0 else points[i]
        p1, p2 = points[i], points[i + 1]
        p3 = points[i + 2] if i + 2 < n else points[i + 1]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0)
        out.append(
            f" C {c1[0]:.2f} {c1[1]:.2f}, {c2[0]:.2f} {c2[1]:.2f}, {p2[0]:.2f} {p2[1]:.2f}"
        )
    return "".join(out)


# ------------------------------------------------------------------------- drawing


def panel(width: int, height: int) -> str:
    return (
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="16" '
        f'fill="{PANEL}" stroke="{PANEL_EDGE}"/>'
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="16" '
        f'fill="url(#topglow)"/>'
    )


def glow_defs() -> str:
    return (
        '<linearGradient id="topglow" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#6df3ff" stop-opacity="0.10"/>'
        '<stop offset="0.55" stop-color="#6df3ff" stop-opacity="0"/>'
        "</linearGradient>"
    )


def kicker(x: int, y: int, text: str) -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="11" font-weight="600" '
        f'letter-spacing="2.6" fill="#5d6b83">{text}</text>'
    )


def live_badge(x: int, y: int) -> str:
    return (
        f'<g><circle cx="{x}" cy="{y - 4}" r="4" fill="#3ddc97">'
        '<animate attributeName="r" values="3;5.2;3" dur="2.4s" repeatCount="indefinite"/>'
        '<animate attributeName="opacity" values="1;0.3;1" dur="2.4s" repeatCount="indefinite"/>'
        "</circle>"
        f'<text x="{x + 13}" y="{y}" font-family="{FONT}" font-size="11" font-weight="600" '
        f'letter-spacing="1.6" fill="#4d5c74">LIVE</text></g>'
    )


def render_heatmap(days: list[tuple[dt.date, int, int]], total: int) -> str:
    weeks = week_starts(days)
    counts = {(d): (c, l) for d, c, l in days}
    cols = max(len(weeks), 1)

    cell, gap, step = 11, 3, 14
    left, top = 52, 112
    gw = cols * step - gap
    gh = 7 * step - gap
    width = W
    height = top + gh + 66

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="Contribution heatmap">',
        "<defs>",
        glow_defs(),
        '<clipPath id="gridclip">'
        f'<rect x="{left}" y="{top}" width="{gw}" height="{gh}" rx="5"/></clipPath>',
        '<linearGradient id="shine" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0" stop-color="#bff9ff" stop-opacity="0"/>'
        '<stop offset="0.5" stop-color="#bff9ff" stop-opacity="0.55"/>'
        '<stop offset="1" stop-color="#bff9ff" stop-opacity="0"/>'
        "</linearGradient>",
        "<style>",
        ".c{animation:pop .55s cubic-bezier(.16,.84,.24,1) both;"
        "transform-box:fill-box;transform-origin:center}",
        "@keyframes pop{from{opacity:0;transform:scale(.3)}to{opacity:1;transform:scale(1)}}",
        "</style>",
        "</defs>",
        panel(width, height),
        kicker(left, 34, "CONTRIBUTIONS \u00b7 LAST 12 MONTHS"),
        live_badge(width - 74, 34),
        f'<text x="{left}" y="76" font-family="{FONT}" font-size="30" font-weight="700" '
        f'fill="{INK}" letter-spacing="-0.5">{total:,}</text>',
        f'<text x="{left + 8 + len(f"{total:,}") * 17}" y="75" font-family="{FONT}" '
        f'font-size="13" fill="{MUTED}">contributions in the last year</text>',
    ]

    # month labels
    previous_month = None
    for index, week in enumerate(weeks):
        month = week.month
        if previous_month is None or month != previous_month:
            if index < cols - 1:
                out.append(
                    f'<text x="{left + index * step}" y="{top - 14}" font-family="{FONT}" '
                    f'font-size="10.5" font-weight="600" letter-spacing="0.6" '
                    f'fill="#5d6b83">{week.strftime("%b")}</text>'
                )
        previous_month = month

    # weekday labels
    for row, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        out.append(
            f'<text x="{left - 12}" y="{top + row * step + 9}" font-family="{FONT}" '
            f'font-size="10" text-anchor="end" fill="#4d5c74">{label}</text>'
        )

    # cells
    for index, week in enumerate(weeks):
        for row in range(7):
            date = week + dt.timedelta(days=row)
            if date not in counts:
                continue
            count, level = counts[date]
            x = left + index * step
            y = top + row * step
            delay = int(index * 7 + row * 16)
            extra = (
                ' stroke="#9df8ff" stroke-opacity="0.45" stroke-width="1"'
                if level >= 4
                else ""
            )
            out.append(
                f'<rect class="c" x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2.6" '
                f'fill="{LEVELS[max(0, min(4, level))]}"{extra} '
                f'style="animation-delay:{delay}ms">'
                f"<title>{date.isoformat()}: {count} contribution"
                f"{'' if count == 1 else 's'}</title></rect>"
            )

    # slow light sweep across the grid
    out.append(
        '<g clip-path="url(#gridclip)" opacity="0.2">'
        f'<rect x="0" y="{top}" width="120" height="{gh}" fill="url(#shine)">'
        '<animateTransform attributeName="transform" type="translate" '
        f'from="-240 0" to="{width + 120} 0" dur="7.5s" begin="1.4s" '
        'repeatCount="indefinite"/></rect></g>'
    )

    # legend
    legend_y = top + gh + 32
    out.append(
        f'<text x="{width - 210}" y="{legend_y + 4}" font-family="{FONT}" font-size="11" '
        f'fill="#4d5c74">Less</text>'
    )
    for i, color in enumerate(LEVELS):
        out.append(
            f'<rect x="{width - 176 + i * 15}" y="{legend_y - 6}" width="11" height="11" '
            f'rx="2.6" fill="{color}"/>'
        )
    out.append(
        f'<text x="{width - 92}" y="{legend_y + 4}" font-family="{FONT}" font-size="11" '
        f'fill="#4d5c74">More</text>'
    )
    out.append("</svg>")
    return "".join(out)


def render_stats(values: list[tuple[str, str]]) -> str:
    height = 128
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" '
        f'viewBox="0 0 {W} {height}" role="img" aria-label="Profile stats">',
        "<defs>", glow_defs(),
        "<style>",
        ".s{animation:rise .7s cubic-bezier(.16,.84,.24,1) both}",
        "@keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}",
        "</style>",
        "</defs>",
        panel(W, height),
    ]
    column = W / 4.0
    for index, (label, value) in enumerate(values[:4]):
        cx = column * (index + 0.5)
        delay = int(index * 90)
        out.append(
            f'<g class="s" style="animation-delay:{delay}ms">'
            f'<text x="{cx}" y="62" text-anchor="middle" font-family="{FONT}" font-size="34" '
            f'font-weight="700" letter-spacing="-0.8" fill="{ACCENTS[index % len(ACCENTS)]}">'
            f"{value}</text>"
            f'<text x="{cx}" y="88" text-anchor="middle" font-family="{FONT}" font-size="10.5" '
            f'font-weight="600" letter-spacing="2.2" fill="#5d6b83">{label.upper()}</text></g>'
        )
        if index:
            out.append(
                f'<line x1="{column * index}" y1="38" x2="{column * index}" y2="92" '
                f'stroke="{PANEL_EDGE}"/>'
            )
    out.append("</svg>")
    return "".join(out)


def render_activity(days: list[tuple[dt.date, int, int]]) -> str:
    counts = {d: c for d, c, _l in days}
    today = dt.date.today()
    window = 90
    series = [counts.get(today - dt.timedelta(days=window - 1 - i), 0) for i in range(window)]

    height = 196
    left, right, base, ceiling = 54, W - 54, 156, 84
    plot_w = right - left
    peak = max(series) or 1

    points = []
    for i, value in enumerate(series):
        x = left + plot_w * i / (window - 1)
        y = base - (value / peak) * (base - ceiling)
        points.append((x, y))

    line = smooth_path(points)
    area = line + f" L {right:.2f} {base} L {left:.2f} {base} Z"
    recent = sum(series)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" '
        f'viewBox="0 0 {W} {height}" role="img" aria-label="90 day activity">',
        "<defs>",
        glow_defs(),
        '<linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#6df3ff" stop-opacity="0.35"/>'
        '<stop offset="1" stop-color="#6df3ff" stop-opacity="0"/>'
        "</linearGradient>",
        '<linearGradient id="stroke" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0" stop-color="#6df3ff"/>'
        '<stop offset="0.55" stop-color="#8b9dff"/>'
        '<stop offset="1" stop-color="#d18bff"/>'
        "</linearGradient>",
        "<style>",
        ".draw{stroke-dasharray:1;stroke-dashoffset:1;animation:draw 2.4s cubic-bezier(.3,.7,.2,1) .15s forwards}",
        "@keyframes draw{to{stroke-dashoffset:0}}",
        ".fade{animation:fade 1.6s ease 1.1s both}",
        "@keyframes fade{from{opacity:0}to{opacity:1}}",
        "</style>",
        "</defs>",
        panel(W, height),
        kicker(left, 36, "PULSE \u00b7 LAST 90 DAYS"),
        f'<text x="{left}" y="72" font-family="{FONT}" font-size="24" font-weight="700" '
        f'fill="{INK}">{recent:,}</text>',
        f'<text x="{left + 10 + len(f"{recent:,}") * 13}" y="71" font-family="{FONT}" '
        f'font-size="12.5" fill="{MUTED}">contributions \u00b7 peak day {peak}</text>',
        f'<path d="{area}" fill="url(#fill)" class="fade"/>',
        f'<path d="{line}" fill="none" stroke="url(#stroke)" stroke-width="2.4" '
        f'stroke-linecap="round" pathLength="1" class="draw"/>',
        f'<line x1="{left}" y1="{base}" x2="{right}" y2="{base}" stroke="{PANEL_EDGE}"/>',
        f'<text x="{left}" y="{base + 24}" font-family="{FONT}" font-size="10.5" '
        f'fill="#4d5c74">90 days ago</text>',
        f'<text x="{right}" y="{base + 24}" text-anchor="end" font-family="{FONT}" '
        f'font-size="10.5" fill="#4d5c74">today</text>',
    ]

    last_x, last_y = points[-1]
    out.append(
        f'<circle cx="{last_x:.2f}" cy="{last_y:.2f}" r="4.5" fill="#6df3ff" class="fade">'
        '<animate attributeName="r" values="3.6;5.4;3.6" dur="2.6s" repeatCount="indefinite"/>'
        f"</circle>"
        f'<circle cx="{last_x:.2f}" cy="{last_y:.2f}" r="10" fill="none" '
        f'stroke="#6df3ff" stroke-opacity="0.35" class="fade"/>'
    )
    out.append("</svg>")
    return "".join(out)


def render_languages(languages: list[tuple[str, float]]) -> str:
    height = 208
    cx, cy, radius, thickness = 128, 122, 58, 18
    circumference = 2 * math.pi * radius
    top = languages[:5]
    if not top:
        top = [("TypeScript", 100.0)]
    rest = sum(p for _n, p in languages[5:]) if len(languages) > 5 else 0.0
    segments = list(top)
    if rest > 0.4:
        segments.append(("Other", rest))
    segments = [(n, p) for n, p in segments if p >= 0.4]

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" '
        f'viewBox="0 0 {W} {height}" role="img" aria-label="Language breakdown">',
        "<defs>", glow_defs(),
        "<style>",
        ".bar{transform-box:fill-box;transform-origin:left center;"
        "animation:grow 1s cubic-bezier(.16,.84,.24,1) both}",
        "@keyframes grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}",
        ".txt{animation:fadin .8s ease both}",
        "@keyframes fadin{from{opacity:0}to{opacity:1}}",
        "</style>",
        "</defs>",
        panel(W, height),
        kicker(54, 36, "STACK \u00b7 BY CODE VOLUME"),
        f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="#151d2b" '
        f'stroke-width="{thickness}"/>',
    ]

    offset = 0.0
    for index, (name, pct) in enumerate(segments):
        color = LANG_COLORS.get(name) or FALLBACK_COLORS[index % len(FALLBACK_COLORS)]
        length = circumference * pct / 100.0
        out.append(
            f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="{color}" '
            f'stroke-width="{thickness}" stroke-dasharray="{length:.2f} {circumference - length:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})" opacity="0">'
            f'<animate attributeName="opacity" values="0;1" dur="0.55s" '
            f'begin="{index * 0.1:.2f}s" fill="freeze"/></circle>'
        )
        offset += length

    out.append(
        f'<text x="{cx}" cy="0" y="{cy - 2}" text-anchor="middle" font-family="{FONT}" '
        f'font-size="26" font-weight="700" fill="{INK}">{len(languages) or 1}</text>'
        f'<text x="{cx}" y="{cy + 18}" text-anchor="middle" font-family="{FONT}" '
        f'font-size="10" font-weight="600" letter-spacing="1.8" fill="#5d6b83">LANGUAGES</text>'
    )

    row_x, bar_x, bar_w = 274, 452, 330
    for index, (name, pct) in enumerate(segments):
        color = LANG_COLORS.get(name) or FALLBACK_COLORS[index % len(FALLBACK_COLORS)]
        y = 60 + index * 26
        out.append(
            f'<g class="txt" style="animation-delay:{120 + index * 80}ms">'
            f'<circle cx="{row_x + 4}" cy="{y - 4}" r="4" fill="{color}"/>'
            f'<text x="{row_x + 18}" y="{y}" font-family="{FONT}" font-size="12.5" '
            f'font-weight="600" fill="{INK}">{name}</text>'
            f'<rect class="bar" x="{bar_x}" y="{y - 9}" width="{bar_w}" height="7" rx="3.5" '
            f'fill="#151d2b"/>'
            f'<rect class="bar" x="{bar_x}" y="{y - 9}" width="{bar_w * pct / 100.0:.1f}" '
            f'height="7" rx="3.5" fill="{color}" style="animation-delay:{160 + index * 80}ms"/>'
            f'<text x="{W - 52}" y="{y}" text-anchor="end" font-family="{FONT}" '
            f'font-size="12" font-weight="600" fill="{MUTED}">{pct:.1f}%</text></g>'
        )

    out.append("</svg>")
    return "".join(out)


def render_banner() -> str:
    width, height = W, 190
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="Hyawii">',
        "<defs>",
        glow_defs(),
        '<linearGradient id="name" x1="0" y1="0" x2="1" y2="0" spreadMethod="reflect" '
        'gradientUnits="objectBoundingBox">'
        '<stop offset="0" stop-color="#6df3ff"/>'
        '<stop offset="0.4" stop-color="#8b9dff"/>'
        '<stop offset="0.7" stop-color="#d18bff"/>'
        '<stop offset="1" stop-color="#ff8bd0"/>'
        '<animateTransform attributeName="gradientTransform" type="translate" '
        'values="-0.6 0; 0.6 0; -0.6 0" dur="11s" repeatCount="indefinite"/>'
        "</linearGradient>",
        '<linearGradient id="rule" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0" stop-color="#6df3ff" stop-opacity="0"/>'
        '<stop offset="0.5" stop-color="#8b9dff" stop-opacity="0.9"/>'
        '<stop offset="1" stop-color="#ff8bd0" stop-opacity="0"/>'
        "</linearGradient>",
        "</defs>",
        panel(width, height),
        f'<text x="{width / 2}" y="102" text-anchor="middle" font-family="{FONT}" '
        f'font-size="66" font-weight="800" letter-spacing="10" fill="url(#name)">HYAWII</text>',
        f'<text x="{width / 2}" y="132" text-anchor="middle" font-family="{FONT}" '
        f'font-size="13.5" letter-spacing="3.4" fill="#7d8aa3">I JUST CODE ANYTHING</text>',
        f'<rect x="{width / 2 - 150}" y="152" width="300" height="2" fill="url(#rule)">'
        '<animate attributeName="opacity" values="0.45;1;0.45" dur="5.5s" '
        'repeatCount="indefinite"/></rect>',
    ]
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------------------- main


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    print(f"collecting {USER}")

    calendar = fetch_calendar()
    days = calendar["days"]
    print(f"  {len(days)} days, {calendar['total']} contributions")

    current_streak, longest_streak = streaks(days)
    active_days = sum(1 for _d, c, _l in days if c > 0)

    try:
        repos = fetch_repos()
        languages = fetch_languages(repos)
    except Exception as err:  # noqa: BLE001 - keep the cards even if the API hiccups
        print(f"  repo lookup failed ({err})")
        repos, languages = [], []
    print(f"  {len(repos)} repos, {len(languages)} languages")

    stars = sum(r.get("stargazers_count", 0) for r in repos if not r.get("fork"))

    if calendar["prs"] is not None:
        stats = [
            ("contributions", f"{calendar['total']:,}"),
            ("commits", f"{calendar['commits']:,}"),
            ("pull requests", f"{calendar['prs']:,}"),
            ("day streak", f"{current_streak}"),
        ]
    else:
        stats = [
            ("contributions", f"{calendar['total']:,}"),
            ("active days", f"{active_days}"),
            ("longest run", f"{longest_streak}"),
            ("day streak", f"{current_streak}"),
        ]

    cards = {
        "banner.svg": render_banner(),
        "heatmap.svg": render_heatmap(days, calendar["total"]),
        "stats.svg": render_stats(stats),
        "activity.svg": render_activity(days),
        "languages.svg": render_languages(languages),
    }
    for name, svg in cards.items():
        path = os.path.join(OUT, name)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(svg)
        print(f"  wrote assets/{name} ({len(svg) / 1024:.1f} KB)")

    meta = {
        "user": USER,
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_contributions": calendar["total"],
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "active_days": active_days,
        "public_repos": len(repos),
        "stars": stars,
        "top_languages": [{"name": n, "percent": round(p, 2)} for n, p in languages[:5]],
    }
    with open(os.path.join(OUT, "data.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    print("  wrote assets/data.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
