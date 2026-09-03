#!/usr/bin/env python3
"""Render a line/area SVG of a GitHub user's commit-count over a rolling window.

Contributions are aggregated into fixed-size buckets (default: weekly) so the
resulting line stays smooth over a long window.

Env vars:
  GH_USER       — GitHub login to fetch (required)
  GITHUB_TOKEN  — token with default read scope (required)
  DAYS          — rolling window in days (default 365)
  BUCKET_DAYS   — bucket size for aggregation (default 7)
  SMOOTHING     — Catmull-Rom smoothing factor, 0.0=linear, 1.0=very round (default 0.5)
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
DAYS = int(os.environ.get("DAYS", "365"))
BUCKET_DAYS = int(os.environ.get("BUCKET_DAYS", "7"))
SMOOTHING = float(os.environ.get("SMOOTHING", "0.5"))
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

days: list[tuple[date, int]] = []
for week in payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
    for d in week["contributionDays"]:
        days.append((date.fromisoformat(d["date"]), d["contributionCount"]))
days.sort()
days = days[-DAYS:]

# Bucket from the right so the most recent bucket ends on today. A leftover
# partial bucket at the far left is dropped so every point represents a full
# BUCKET_DAYS window.
buckets: list[tuple[date, int]] = []
i = len(days)
while i - BUCKET_DAYS >= 0:
    chunk = days[i - BUCKET_DAYS:i]
    buckets.append((chunk[0][0], sum(c for _, c in chunk)))
    i -= BUCKET_DAYS
buckets.reverse()

if not buckets:
    print("no full buckets in window", file=sys.stderr)
    sys.exit(1)

W, H = 1200, 400
PAD_L, PAD_R, PAD_T, PAD_B = 60, 40, 40, 40
plot_w = W - PAD_L - PAD_R
plot_h = H - PAD_T - PAD_B
max_c = max(c for _, c in buckets) or 1
step_x = plot_w / max(len(buckets) - 1, 1)


def px(i: int) -> float:
    return PAD_L + i * step_x


def py(c: float) -> float:
    return PAD_T + plot_h * (1 - c / max_c)


line_pts = [(px(i), py(c)) for i, (_, c) in enumerate(buckets)]


def smoothed_path(pts: list[tuple[float, float]]) -> str:
    """Cubic-Bezier path through pts using a cardinal (Catmull-Rom) spline.

    SMOOTHING controls curviness: 0.0 gives straight segments, 1.0 gives a
    very rounded curve that may overshoot near sharp value changes.
    """
    if not pts:
        return ""
    if len(pts) == 1:
        return f"M {pts[0][0]:.2f},{pts[0][1]:.2f}"
    parts = [f"M {pts[0][0]:.2f},{pts[0][1]:.2f}"]
    k = SMOOTHING / 3.0
    n = len(pts)
    for i in range(n - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1 = pts[i]
        p2 = pts[i + 1]
        p3 = pts[i + 2] if i + 2 < n else pts[i + 1]
        cp1x = p1[0] + (p2[0] - p0[0]) * k
        cp1y = p1[1] + (p2[1] - p0[1]) * k
        cp2x = p2[0] - (p3[0] - p1[0]) * k
        cp2y = p2[1] - (p3[1] - p1[1]) * k
        parts.append(
            f"C {cp1x:.2f},{cp1y:.2f} {cp2x:.2f},{cp2y:.2f} {p2[0]:.2f},{p2[1]:.2f}"
        )
    return " ".join(parts)


line_d = smoothed_path(line_pts)
baseline_y = py(0)
area_d = (
    f"{line_d} "
    f"L {line_pts[-1][0]:.2f},{baseline_y:.2f} "
    f"L {line_pts[0][0]:.2f},{baseline_y:.2f} Z"
)

# X-axis month ticks placed on the first bucket that starts a new month.
month_ticks: list[tuple[int, str]] = []
prev_month = None
for i, (d, _) in enumerate(buckets):
    if d.month != prev_month:
        month_ticks.append((i, d.strftime("%b")))
        prev_month = d.month

# Y-axis: 0, mid, max — rounded to a nice-looking integer where possible.
y_ticks = sorted({0, max_c // 2, max_c}) if max_c > 1 else [0, 1]
total = sum(c for _, c in buckets)

# Nord palette
BG = "#2e3440"
FG = "#eceff4"
AXIS = "#d8dee9"
GRID = "#3b4252"
LINE = "#88c0d0"
AREA = "#88c0d044"

title = (
    f"Commits per {BUCKET_DAYS}d — last {len(buckets) * BUCKET_DAYS} days "
    f"({buckets[0][0]} → {days[-1][0]}, total {total})"
)

out = [
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
    f'font-family="\'Segoe UI\',Ubuntu,Sans-Serif">',
    f'  <rect width="{W}" height="{H}" fill="{BG}"/>',
    f'  <text x="{PAD_L}" y="22" fill="{FG}" font-size="16" font-weight="600">{title}</text>',
    f'  <g stroke="{GRID}" stroke-width="1">',
]
for c in y_ticks:
    yy = py(c)
    out.append(f'    <line x1="{PAD_L}" x2="{W - PAD_R}" y1="{yy:.2f}" y2="{yy:.2f}"/>')
out.append('  </g>')
out.append(f'  <g fill="{AXIS}" font-size="12">')
for c in y_ticks:
    out.append(f'    <text x="{PAD_L - 8}" y="{py(c) + 4:.2f}" text-anchor="end">{c}</text>')
for i, m in month_ticks:
    out.append(f'    <text x="{px(i):.2f}" y="{H - PAD_B + 20}" text-anchor="middle">{m}</text>')
out.append('  </g>')
out.append(f'  <path d="{area_d}" fill="{AREA}"/>')
out.append(
    f'  <path d="{line_d}" fill="none" stroke="{LINE}" '
    'stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>'
)
out.append('</svg>')

os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
with open(OUTPUT, "w") as f:
    f.write("\n".join(out) + "\n")
print(
    f"Wrote {OUTPUT} — {len(buckets)} buckets × {BUCKET_DAYS}d "
    f"= {len(buckets) * BUCKET_DAYS} days, max/bucket={max_c}, total={total}"
)
