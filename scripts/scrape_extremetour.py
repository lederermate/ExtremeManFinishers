#!/usr/bin/env python3
"""Letölti az extremetour.hu finisher-adatait (teljes táv, egyéni) évenként.

Kimenet: data/extremetour.json
  {
    "athletes": {"<id>": "<név>"},
    "results":  [{"athlete_id": 1039, "year": 1991, "pos": 12, "time": "11:24:00"}, ...],
    "abc":      {"<id>": {"best": "10:36:00", "count": 32}}   # ellenőrzéshez
  }

Használat:  python3 scripts/scrape_extremetour.py
"""
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

BASE = "https://www.extremetour.hu"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "extremetour.json"

ROW_YEAR = re.compile(
    r'<tr[^>]*>\s*<td[^>]*>\s*(\d+)\s*</td>\s*'
    r'<td[^>]*>\s*<a href="/?finisher/(\d+)"[^>]*>(.*?)</a>\s*</td>\s*'
    r'<td[^>]*>\s*([\d:]+)\s*</td>',
    re.S,
)
ROW_ABC = re.compile(
    r'<tr[^>]*>\s*<td[^>]*>\s*<a href="/?finisher/(\d+)"[^>]*>(.*?)</a>\s*</td>\s*'
    r'<td[^>]*>\s*([\d:]+)\s*</td>\s*<td[^>]*>\s*(\d+)\s*</td>',
    re.S,
)


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ExtremeManFinishers importer"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def clean(name: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(name)).strip()


def main() -> None:
    ev = get(f"{BASE}/finisherekevlista")
    years = sorted({int(y) for y in re.findall(r"finisherekevben/(\d{4})", ev)})
    print("Évek:", years[0], "–", years[-1], f"({len(years)} db)")

    athletes: dict[str, str] = {}
    results = []
    for y in years:
        page = get(f"{BASE}/finisherekevben/{y}")
        rows = ROW_YEAR.findall(page)
        for pos, aid, name, t in rows:
            athletes.setdefault(aid, clean(name))
            results.append({"athlete_id": int(aid), "year": y, "pos": int(pos), "time": t})
        print(f"  {y}: {len(rows)} célba érkező")
        time.sleep(0.5)

    abc_page = get(f"{BASE}/finisherekabc")
    abc = {}
    for aid, name, best, cnt in ROW_ABC.findall(abc_page):
        abc[aid] = {"best": best, "count": int(cnt)}
        athletes.setdefault(aid, clean(name))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"athletes": athletes, "results": results, "abc": abc}, ensure_ascii=False, indent=0),
        encoding="utf-8",
    )
    print(f"Kész: {len(athletes)} versenyző, {len(results)} eredmény -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
