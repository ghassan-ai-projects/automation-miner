"""Inline stylesheet for the stakeholder one-pager: print-ready, light and dark."""

from __future__ import annotations

ONE_PAGER_CSS = """
:root {
  --bg: #ffffff; --fg: #1d2330; --muted: #5d6676; --line: #dfe3ea; --card: #f7f8fa;
  --accent: #2f5bd3; --vision: #6b3fd1; --high: #1f7a4d; --medium: #946200; --low: #8a8f98;
  --warn: #a4471b;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #12151b; --fg: #e6e9ef; --muted: #9aa3b2; --line: #2a303b; --card: #1a1f27;
    --accent: #7c9cff; --vision: #b294ff; --high: #5fcf97; --medium: #e0b552;
    --low: #a1a7b1; --warn: #f0956b;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font: 15px/1.5 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
main { max-width: 960px; margin: 0 auto; padding: 32px 16px 48px; }
h1 { font-size: 26px; line-height: 1.25; margin: 0 0 4px; }
h2 { font-size: 18px; margin: 32px 0 12px; border-bottom: 1px solid var(--line); padding-bottom: 6px; }
h3 { font-size: 17px; margin: 0 0 8px; }
h4 { font-size: 13px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted);
     margin: 14px 0 4px; }
p { margin: 0 0 8px; }
a { color: var(--accent); }
ul { margin: 0; padding-left: 20px; }
.meta { color: var(--muted); margin-bottom: 16px; }
.facts { display: flex; flex-wrap: wrap; gap: 8px 24px; margin: 12px 0 0; }
.facts div { min-width: 120px; }
.facts b { display: block; font-size: 20px; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
        padding: 18px 20px; margin: 0 0 16px; break-inside: avoid; }
.badges { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 10px; }
.badge { font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 999px;
         border: 1px solid var(--line); color: var(--muted); }
.tier-vision { color: var(--vision); border-color: var(--vision); }
.tier-high { color: var(--high); border-color: var(--high); }
.tier-medium { color: var(--medium); border-color: var(--medium); }
.tier-low { color: var(--low); border-color: var(--low); }
.hypothesis { color: var(--warn); border-color: var(--warn); }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 0 24px; }
.assumed { color: var(--muted); font-size: 12px; }
footer { color: var(--muted); font-size: 13px; margin-top: 32px; }
@media (max-width: 640px) {
  .cols { grid-template-columns: 1fr; } h1 { font-size: 22px; } .wide { display: none; }
}
@media print {
  :root { --bg: #fff; --fg: #000; --card: #fff; }
  main { padding: 0; max-width: none; }
  .card { border-color: #bbb; }
}
"""
