#!/usr/bin/env python3
"""Render a line/area SVG of a GitHub user's daily commit-count over a rolling window.

Env vars:
  GH_USER       — GitHub login to fetch (required)
  GITHUB_TOKEN  — token with default read scope (required)
  DAYS          — rolling window in days (default 180)
  OUTPUT        — output SVG path (default assets/commit-graph.svg)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import date, timedelta

USER = os.environ["GH_USER"]
TOKEN = os.environ["GITHUB_TOKEN"]
DAYS = int(os.environ.get("DAYS", "180"))
OUTPUT = os.environ.get("OUTPUT", "assets/commit-graph.svg")

QUERY = """
query($user: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $user) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""

today = date.today()
start = today - timedelta(days=DAYS - 1)
variables = {
    "user": USER,
    "from": f"{start.isoformat()}T00:00:00Z",
    "to": f"{today.isoformat()}T23:59:59Z",
}

req = urllib.request.Request(
    "https://api.github.com/graphql",
    data=json.dumps({"query": QUERY, "variables": variables}).encode(),
    headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "commit-graph-generator",
    },
)
with urllib.request.urlopen(req) as res:
    payload = json.loads(res.read())

if "errors" in payload:
    print(json.dumps(payload, indent=2), file=sys.stderr)
    sys.exit(1)

days: list[tuple[str, int]] = []
for week in payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
    for d in week["contributionDays"]:
        days.append((d["date"], d["contributionCount"]))
days.sort()
days = days[-DAYS:]

W, H = 1200, 400
PAD_L, PAD_R, PAD_T, PAD_B = 60, 20, 40, 40
plot_w = W - PAD_L - PAD_R
plot_h = H - PAD_T - PAD_B
max_c = max((c for _, c in days), default=1) or 1
step_x = plot_w / max(len(days) - 1, 1)


def x(i: int) -> float:
    return PAD_L + i * step_x


def y(c: int) -> float:
    return PAD_T + plot_h * (1 - c / max_c)


line_pts = " ".join(f"{x(i):.2f},{y(c):.2f}" for i, (_, c) in enumerate(days))
area_pts = f"{x(0):.2f},{y(0):.2f} {line_pts} {x(len(days) - 1):.2f},{y(0):.2f}"

month_ticks: list[tuple[int, str]] = []
prev_month = None
for i, (d, _) in enumerate(days):
    dt = date.fromisoformat(d)
    if dt.month != prev_month:
        month_ticks.append((i, dt.strftime("%b")))
        prev_month = dt.month

y_ticks = sorted({0, max_c // 2, max_c}) if max_c > 1 else [0, 1]
total = sum(c for _, c in days)

# Nord palette to match existing profile cards
BG = "#2e3440"
FG = "#eceff4"
MUTED = "#4c566a"
GRID = "#3b4252"
LINE = "#88c0d0"
AREA = "#88c0d044"

out = [
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
    f'font-family="\'Segoe UI\',Ubuntu,Sans-Serif">',
    f'  <rect width="{W}" height="{H}" fill="{BG}"/>',
    f'  <text x="{PAD_L}" y="22" fill="{FG}" font-size="16" font-weight="600">'
    f'Commits — last {len(days)} days ({days[0][0]} → {days[-1][0]}, total {total})</text>',
    '  <g stroke="' + GRID + '" stroke-width="1">',
]
for c in y_ticks:
    yy = y(c)
    out.append(f'    <line x1="{PAD_L}" x2="{W - PAD_R}" y1="{yy:.2f}" y2="{yy:.2f}"/>')
out.append('  </g>')
out.append(f'  <g fill="{MUTED}" font-size="12">')
for c in y_ticks:
    out.append(f'    <text x="{PAD_L - 8}" y="{y(c) + 4:.2f}" text-anchor="end">{c}</text>')
for i, m in month_ticks:
    out.append(f'    <text x="{x(i):.2f}" y="{H - PAD_B + 20}" text-anchor="middle">{m}</text>')
out.append('  </g>')
out.append(f'  <polygon points="{area_pts}" fill="{AREA}"/>')
out.append(
    f'  <polyline points="{line_pts}" fill="none" stroke="{LINE}" '
    'stroke-width="2" stroke-linejoin="round"/>'
)
out.append('</svg>')

os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
with open(OUTPUT, "w") as f:
    f.write("\n".join(out) + "\n")
print(f"Wrote {OUTPUT} — {len(days)} days, max={max_c}, total={total}")
