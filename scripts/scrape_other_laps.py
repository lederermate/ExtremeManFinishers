#!/usr/bin/env python3
"""Köztes mérőpontok a "további" eXtremeMan versenyekre (data/races/*.json alapján).

Minden versenynél (esemény + táv) a célba érkezők EvoChip adatlapját tölti le,
és kiírja: data/laps_other/<verseny-kulcs>.json  (rajtszám -> [[összidő, köridő, helyezés], ...])
A már kész versenyeket kihagyja; a letöltött oldalak a .cache/evochip/ alatt maradnak.

Használat: python3 scripts/scrape_other_laps.py   (a legfrissebb versenyekkel kezd)
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import scrape_evochip_laps as S  # noqa: E402

OUT = ROOT / "data" / "laps_other"


def list_pids_all(event: str, distance: str) -> dict:
    """rajtszám -> pid a táv teljes listájából (kategória nélkül)."""
    out, page = {}, 1
    while True:
        t = S.get({"eventid": event, "category": "none", "page": page}, f"{event}/list_{distance or 'all'}_none_{page}.html")
        for pid, bib in re.findall(r"pid=(\d+)[^>]*>[^<]*</a>.*?Rsz:&nbsp;</b>\s*(\d+)", t, re.S):
            out.setdefault(int(bib), pid)
        last = max([int(x) for x in re.findall(r"page=(\d+)", t)] or [1])
        if page >= last:
            break
        page += 1
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    races = [json.loads(f.read_text(encoding="utf-8")) for f in (ROOT / "data" / "races").glob("2*.json")]
    races.sort(key=lambda r: (-r["year"], r["key"]))
    for rc in races:
        out_f = OUT / f"{rc['key']}.json"
        if out_f.exists():
            continue
        S.DISTANCE = rc["distance"] or ""
        bibs = {int(r["bib"]) for r in rc["rows"] if isinstance(r.get("bib"), int) or str(r.get("bib") or "").isdigit()}
        try:
            pids = list_pids_all(rc["event"], rc["distance"])
        except Exception as e:  # noqa: BLE001
            print(f"{rc['key']}: lista hiba ({e})", flush=True)
            continue
        points, athletes = [], {}
        for bib in sorted(bibs):
            if bib not in pids:
                continue
            try:
                t = S.get({"eventid": rc["event"], "category": "none", "pid": pids[bib]}, f"{rc['event']}/pid_{pids[bib]}.html")
            except Exception as e:  # noqa: BLE001
                print(f"  ! {rc['key']} #{bib}: {e}", flush=True)
                continue
            pts = S.parse_detail(t)
            if not pts:
                continue
            if not points:
                points = [{"label": p["label"], "disc": p["disc"], "km": p["km"]} for p in pts]
            if [p["label"] for p in pts] != [p["label"] for p in points]:
                by = {p["label"]: p for p in pts}
                pts = [by.get(p["label"], {"cum": None, "lap": None, "rank": None}) for p in points]
            athletes[str(bib)] = [[p["cum"], p["lap"], p["rank"]] for p in pts]
        out_f.write_text(json.dumps({"key": rc["key"], "year": rc["year"], "points": points, "athletes": athletes},
                                    ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"{rc['key']}: {len(athletes)}/{len(bibs)} versenyző, {len(points)} mérőpont", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
