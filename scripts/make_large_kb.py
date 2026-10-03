"""Generate a deterministic large knowledge base for the quality suite.

The three hand-written cases fit in every stage's evidence budget, so the
digest and BM25 selection paths never run against a real provider. This
writes 21 synthetic field-service documents (~100k tokens) for a fictional
grid operator: depot SOPs, weekly operations logs, and one work-order export.
The content is synthetic and deterministic (seeded), not a real organization.

    uv run python scripts/make_large_kb.py /tmp/large-kb
"""

from __future__ import annotations

import csv
import random
import sys
from pathlib import Path

DEPOTS = ("Köln-Nord", "Köln-Süd", "Bonn", "Leverkusen", "Bergheim", "Düren",
          "Euskirchen", "Siegburg", "Frechen", "Hürth")
SYSTEMS = ("SAP PM", "FieldLink mobile app", "GridGIS", "Outlook", "Excel dispatch board")
FAULTS = ("meter fault", "cable damage", "transformer alarm", "street light outage",
          "new connection", "smart meter rollout")

SOP = """# Depot {depot} — Field Service SOP (synthetic)

> Synthetic example for automation-miner. Rheinwerk Netze GmbH is fictional.

## Work intake
Dispatchers in {depot} receive about {orders} work orders per week from {system}.
Roughly {email_share}% arrive by email from the customer service centre and are
re-typed into SAP PM, taking {key_minutes} minutes each. Urgent faults are phoned
in and logged on the {board}.

## Scheduling
Technicians are planned the afternoon before on the Excel dispatch board. Route
changes after 07:00 are passed by phone; the team lead estimates {replans}
re-plans per day. Parts availability is checked by calling the central warehouse,
which takes {parts_minutes} minutes per call on average.

## Completion and reporting
Technicians close orders in the FieldLink app, but {paper_share}% still return
paper job sheets that an administrator keys in on Fridays. The weekly SLA report
for the regulator (BNetzA quality-regulation figures) is compiled by hand from
SAP exports and takes about {report_hours} hours.

## Known issues
- {repeat_share}% of fault visits are repeat visits within 30 days.
- Missing parts cause {missed_share}% of first visits to end without a fix.
- New starters need about {ramp_weeks} weeks before they plan routes alone.
"""

LOG = """# Weekly operations log — {depot}, week {week} (synthetic)

Orders received: {orders}. Completed: {done}. Backlog at Friday close: {backlog}.
Emergency faults: {emergencies}; median time to arrive {arrive} minutes.
Overtime hours: {overtime}. Repeat visits: {repeats}.
Notes: {note}
"""

NOTES = (
    "Storm on Tuesday doubled the cable-damage queue; dispatch worked until 22:00.",
    "Warehouse stock-out of 63A fuses delayed 14 jobs.",
    "Two technicians on training; re-plans handled by the team lead by phone.",
    "Regulator data request answered from three separate Excel exports.",
    "Customer service forwarded 40 duplicate fault emails for one street outage.",
)


def _sop(depot: str, rng: random.Random) -> str:
    return SOP.format(
        depot=depot, orders=rng.randint(180, 420), system=rng.choice(SYSTEMS),
        email_share=rng.randint(25, 55), key_minutes=rng.randint(5, 12),
        board=SYSTEMS[4], replans=rng.randint(8, 30), parts_minutes=rng.randint(6, 15),
        paper_share=rng.randint(10, 35), report_hours=rng.randint(4, 9),
        repeat_share=rng.randint(6, 14), missed_share=rng.randint(8, 20),
        ramp_weeks=rng.randint(4, 10),
    )


def _logs(depot: str, rng: random.Random, weeks: int) -> str:
    entries = []
    for week in range(1, weeks + 1):
        orders = rng.randint(180, 420)
        entries.append(LOG.format(
            depot=depot, week=week, orders=orders, done=orders - rng.randint(0, 40),
            backlog=rng.randint(10, 120), emergencies=rng.randint(5, 40),
            arrive=rng.randint(35, 95), overtime=rng.randint(5, 60),
            repeats=rng.randint(10, 50), note=rng.choice(NOTES),
        ))
    return "\n".join(entries)


def _orders_csv(path: Path, rng: random.Random, rows: int) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["order_id", "depot", "type", "channel", "minutes_on_site", "repeat"])
        for index in range(rows):
            writer.writerow([
                f"WO-{100000 + index}", rng.choice(DEPOTS), rng.choice(FAULTS),
                rng.choice(("email", "phone", "portal", "paper")), rng.randint(15, 240),
                rng.random() < 0.1,
            ])


def make_large_kb(target: Path, weeks: int = 104, seed: int = 7) -> Path:
    """Write the knowledge base into ``target`` and return it."""
    rng = random.Random(seed)
    target.mkdir(parents=True, exist_ok=True)
    for depot in DEPOTS:
        slug = depot.lower().replace("ö", "oe").replace("ü", "ue")
        (target / f"sop-{slug}.md").write_text(_sop(depot, rng), encoding="utf-8")
        (target / f"ops-log-{slug}.md").write_text(_logs(depot, rng, weeks), encoding="utf-8")
    _orders_csv(target / "work-orders-2026q2.csv", rng, rows=5_000)
    return target


if __name__ == "__main__":
    print(make_large_kb(Path(sys.argv[1] if len(sys.argv) > 1 else "large-kb")))
