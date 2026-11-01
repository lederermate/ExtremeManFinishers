#!/usr/bin/env python3
"""Letölti az EvoChip egyéni adatlapjairól a köztes mérőpontokat
(úszás körök, kerékpár szakaszok, futás körök) a teljes táv egyéni versenyzőire.

Használat:
  python3 scripts/scrape_evochip_laps.py Nagyatad25VIn 2025            # mindenki
  python3 scripts/scrape_evochip_laps.py Nagyatad24VIn 2024 --bibs 12,34  # csak ezek a rajtszámok
  python3 scripts/scrape_evochip_laps.py Nagyatad18EAr 2018 --distance ''  # 2021 előtti események

Kimenet: data/laps/<év>.json
  {
    "year": 2025,
    "points": [{"label": "Úszás 1", "disc": "swim", "km": 1.27}, ...],   # sorrendben
    "athletes": {"<rajtszám>": [[összidő_s, köridő_s, nemenkénti_helyezés], ...]}
  }
A letöltött oldalak a .cache/evochip/ mappába kerülnek (nem része a repónak),
így egy újrafuttatás nem tölti le őket még egyszer.
"""
import argparse
import html
import json
import re
import time
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "evochip"
DISTANCE = "xman"
BASE = "https://www.evochip.hu/results/result.php"
COMMON = {"timepoint": "none", "lang": "hu", "css": "evochip.css",
          "iframe": "0", "mobile": "1", "viewport": "450"}


def get(params: dict, cache_name: str) -> str:
    f = CACHE / cache_name
    if f.exists():
        return f.read_text(encoding="utf-8")
    url = BASE + "?" + urllib.parse.urlencode({**COMMON, "distance": DISTANCE, **params})
    req = urllib.request.Request(url, headers={"User-Agent": "ExtremeManFinishers importer"})
    for attempt in range(4):  # a szerver néha megszakítja a kapcsolatot
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                text = r.read().decode("utf-8", errors="replace")
            break
        except (OSError, urllib.error.URLError):
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    time.sleep(0.4)
    return text


def to_sec(s: str):
    s = s.strip()
    if not re.fullmatch(r"\d{1,2}(:\d{1,2}){1,2}", s):
        return None
    p = [int(x) for x in s.split(":")]
    while len(p) < 3:
        p.insert(0, 0)
    return p[0] * 3600 + p[1] * 60 + p[2]


def disc_of(label: str):
    l = label.lower()
    if "úsz" in l or "swim" in l:
        return "swim"
    if "kerékp" in l or "kerekp" in l or "bring" in l or "bike" in l or "bicikli" in l:
        return "bike"
    if "kajak" in l or "kayak" in l:
        return "kayak"
    if "fut" in l or "run" in l:
        return "run"
    if "dep" in l:
        return "tr"
    return None


def list_pids(event: str) -> dict:
    """rajtszám -> pid, a férfi és a női abszolút listából."""
    out = {}
    for cat in ("f", "n"):
        page = 1
        while True:
            t = get({"eventid": event, "category": cat, "page": page}, f"{event}/list_{cat}_{page}.html")
            for pid, bib in re.findall(r"pid=(\d+)[^>]*>[^<]*</a>.*?Rsz:&nbsp;</b>\s*(\d+)", t, re.S):
                out.setdefault(int(bib), pid)
            last = max([int(x) for x in re.findall(r"page=(\d+)", t)] or [1])
            if page >= last:
                break
            page += 1
    return out


def parse_detail(t: str):
    i = t.find(">Mérőpont<")
    if i < 0:
        return None
    j = t.find("</table>", i)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", t[i:j], re.S)
    pts = []
    for row in rows:
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) < 6:
            continue
        label = re.sub(r"\s+", " ", cells[0])
        d = disc_of(label)
        if d is None:  # pl. "Összidő (korrigált)"
            continue
        km = re.match(r"([\d.,]+)\s*km", cells[3])
        rank = re.match(r"\d+", cells[5])
        pts.append({
            "label": label, "disc": d,
            "km": float(km.group(1).replace(",", ".")) if km else None,
            "cum": to_sec(cells[1]), "lap": to_sec(cells[2]),
            "rank": int(rank.group(0)) if rank else None,
        })
    return pts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("event")
    ap.add_argument("year", type=int)
    ap.add_argument("--bibs", help="csak ezek a rajtszámok (vesszővel elválasztva)")
    ap.add_argument("--distance", default="xman", help="táv-kód (2021 előtt üres: --distance '')")
    args = ap.parse_args()
    global DISTANCE
    DISTANCE = args.distance

    pids = list_pids(args.event)
    bibs = sorted(pids)
    if args.bibs:
        want = {int(b) for b in args.bibs.split(",")}
        bibs = [b for b in bibs if b in want]
    print(f"{args.year}: {len(pids)} egyéni versenyző a listában, {len(bibs)} adatlap feldolgozása")

    out_f = ROOT / "data" / "laps" / f"{args.year}.json"
    data = json.loads(out_f.read_text(encoding="utf-8")) if out_f.exists() else {"year": args.year, "points": [], "athletes": {}}
    points = data["points"]
    for n, bib in enumerate(bibs, 1):
        t = get({"eventid": args.event, "category": "none", "pid": pids[bib]}, f"{args.event}/pid_{pids[bib]}.html")
        pts = parse_detail(t)
        if not pts:
            continue
        labels = [p["label"] for p in pts]
        if not points:
            points = [{"label": p["label"], "disc": p["disc"], "km": p["km"]} for p in pts]
        if labels != [p["label"] for p in points]:
            # hiányzó mérőpont: a közös sorrendhez igazítjuk
            by = {p["label"]: p for p in pts}
            pts = [by.get(p["label"], {"cum": None, "lap": None, "rank": None}) for p in points]
        data["athletes"][str(bib)] = [[p["cum"], p["lap"], p["rank"]] for p in pts]
        if n % 25 == 0:
            print(f"  {n}/{len(bibs)}")
    data["points"] = points
    out_f.parent.mkdir(parents=True, exist_ok=True)
    out_f.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Kész: {len(data['athletes'])} versenyző, {len(points)} mérőpont -> {out_f.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
