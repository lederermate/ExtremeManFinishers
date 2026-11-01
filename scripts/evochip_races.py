#!/usr/bin/env python3
"""A "további" eXtremeMan versenyek (minden táv a nagyatádi teljes táv kivételével)
letöltése és feldolgozása az EvoChip XLSX exportjaiból.

- Felnőtt egyéni versenyek: triatlon, duatlon, quadrathlon, aquatlon, középtáv
  variációk, Próbáld ki, futóversenyek, ITT.
- KIMARAD: váltók, gyermek / serdülő / ifjúsági / újonc / junior kategóriák,
  és a nagyatádi teljes táv (azt a build_data.py külön kezeli).

Kimenet:
  data/races/catalog.json        a versenyek (esemény + táv) listája
  data/races/<kulcs>.json        egy verseny eredményei (versenyzőnként)
A letöltött fájlok a .cache/evochip/ alá kerülnek.

Használat: python3 scripts/evochip_races.py
"""
import html
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "evochip"
OUT = ROOT / "data" / "races"
BASE = "https://www.evochip.hu/results/"

# EvoChip esemény -> sorozat (kézzel válogatva az évenkénti eseménylistákból)
SERIES = {
    "nagyatad": "Nagyatád – többi táv", "nagyatad-aquatlon": "Nagyatád Aquatlon", "kaposvar": "Kaposvár",
    "velence": "Velence", "szekesfehervar": "Székesfehérvár", "nagocs": "Nágocs",
    "tab": "Tab duatlon", "balatonszemes-duatlon": "Balatonszemes duatlon",
    "balatonszemes": "Balatonszemes triatlon", "gyekenyes": "Gyékényes",
}
EVENTS = [
    (2015, "ExtremeMan113Kaposvar15EAr", "kaposvar"), (2015, "ExtremeMan2575Kaposvar15EAr", "kaposvar"),
    (2015, "ExtremeManVelence15EAr", "velence"),
    (2016, "ExtremeMan113Kaposvar16EAr", "kaposvar"), (2016, "ExtremeMan2575Kaposvar16EAr", "kaposvar"),
    (2016, "ExtremeManVelence16EAr", "velence"), (2016, "NagyatadAqua16DAd", "nagyatad-aquatlon"),
    (2017, "ExtremeMan113Kaposvar17EAr", "kaposvar"), (2017, "ExtremeMan2575Kaposvar17EAr", "kaposvar"),
    (2017, "ExtrememanVelence17DSr", "velence"), (2017, "Nagyatad_Aquatlon17HZt", "nagyatad-aquatlon"),
    (2018, "AquatlonNagyatad18SAm", "nagyatad-aquatlon"), (2018, "Nagocs18HSs", "nagocs"),
    (2018, "SzfvXtremeManTri18SAm", "szekesfehervar"), (2018, "eXtremeMan257518Hfa", "kaposvar"),
    (2018, "eXtrememan113KaposvarSAm18", "kaposvar"),
    (2019, "ExtrMan113Kaposvar19VIn", "kaposvar"), (2019, "ExtrManQ30T2575Kaposvar19VIn", "kaposvar"),
    (2019, "ExtremeManSzekesfehervar19VIn", "szekesfehervar"),
    (2020, "ExtrManQ30Kaposvar20VIn", "kaposvar"),
    (2021, "TabDuatlon21DAd", "tab"), (2021, "eXtremeManKaposvar21DAd", "kaposvar"),
    (2021, "eXtremeManKaposvarKozep21DAd", "kaposvar"), (2021, "eXtremeManSzekesfehervar21DAd", "szekesfehervar"),
    (2022, "Gyekenyes51522VIn", "gyekenyes"), (2022, "Nagyatad22VIn", "nagyatad"),
    (2022, "TabDuatlon22VIn", "tab"), (2022, "eXtremeManKaposvar22VIn", "kaposvar"),
    (2023, "Nagyatad23VIn", "nagyatad"), (2023, "TabDuatlon23VIn", "tab"),
    (2024, "Nagyatad24VIn", "nagyatad"), (2024, "eManDuaBszemes24VIn", "balatonszemes-duatlon"),
    (2024, "eXtremeManKaposvar24VIn", "kaposvar"), (2024, "eXtremen24HFa", "gyekenyes"),
    (2025, "GyekenyesTri25HFa", "gyekenyes"), (2025, "KaposvarTri25HFa", "kaposvar"),
    (2025, "Nagyatad25VIn", "nagyatad"), (2025, "eManDuaBszemes25VIn", "balatonszemes-duatlon"),
    (2025, "eXtremeManBSZ25VIn", "balatonszemes"),
    (2026, "GyekenyesTri26DAd", "gyekenyes"), (2026, "KaposvarTri26HFa", "kaposvar"),
    (2026, "Nagyatad26VIn", "nagyatad"), (2026, "eManDuaBszemes26VIn", "balatonszemes-duatlon"),
    (2026, "eXtremeMan11326HFa", "balatonszemes"),
]
SKIP_DISTANCE = {("nagyatad", "xman"), ("nagyatad", "fun")}  # teljes táv (külön kezelve), váltó
KIDS = re.compile(r"gyermek|serdül|ifj[uú]s|újonc|ujonc|junior|child|youth|12 évesek|diák", re.I)
RELAY = re.compile(r"váltó|valto|relay|csapat", re.I)
META = ("Hely.", "Kat.h.", "Rsz", "Név", "Szül.év", "Klub", "License", "Ország", "Város")
SKIP_EVENT_DISTANCE = {("ExtremeMan2575Kaposvar16EAr", "13")}  # Junior 13


def seg_name(h: str) -> str:
    """A szakaszok neveinek egységesítése (D1, Depo1, 1. Depo -> Depó 1; Swim -> Úszás ...)."""
    x = re.sub(r"\s+", " ", h.strip())
    l = x.lower().replace("ó", "o").replace("á", "a").replace("é", "e")
    m = re.fullmatch(r"(?:d|t|depo|depo ?)(\d)|(\d)\. ?depo|depo (\d)", l)
    if m:
        return f"Depó {next(g for g in m.groups() if g)}"
    if l in ("s", "swim", "uszas"):
        return "Úszás"
    if l in ("b", "bike", "bringa", "kerekpar", "kerekpar", "bicikli", "kerekpár"):
        return "Kerékpár"
    if l in ("r", "futas"):
        return "Futás"
    if l in ("kayak", "kajak"):
        return "Kajak"
    if re.fullmatch(r"(1|elso|1\.) ?fut(as)?|1\. futas|futas ?1|1\. futas", l) or l in ("1fut", "1futas", "elso futas"):
        return "Futás 1"
    if re.fullmatch(r"(2|masodik|2\.) ?fut(as)?|futas ?2", l) or l in ("2fut", "2futas", "masodik futas"):
        return "Futás 2"
    return x


def get(path: str, params: dict, cache_name: str, binary=False):
    f = CACHE / cache_name
    if f.exists():
        return f.read_bytes() if binary else f.read_text(encoding="utf-8")
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "ExtremeManFinishers importer"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    time.sleep(0.4)
    return data if binary else data.decode("utf-8", errors="replace")


def to_sec(v):
    s = str(v or "").strip()
    if not re.fullmatch(r"\d{1,2}(:\d{1,2}){1,2}(\.\d+)?", s):
        return None
    s = s.split(".")[0]
    p = [int(x) for x in s.split(":")]
    while len(p) < 3:
        p.insert(0, 0)
    return p[0] * 3600 + p[1] * 60 + p[2]


def clean(v):
    s = re.sub(r"\s+", " ", str(v)).strip() if v is not None else ""
    return s or None


def distances(event: str):
    t = get("result.php", {"eventid": event, "lang": "hu", "mobile": "1"}, f"{event}/event.html")
    title = re.search(r"<h1>([^<]*)", t)
    title = html.unescape(title.group(1)).strip() if title else event
    m = re.search(r'name="distance".*?</select>', t, re.S)
    ds = [(v, html.unescape(n).strip()) for v, n in re.findall(r'value="([^"]*)">\s*([^<]+)', m.group(0))] if m else []
    return title, ds


def parse_xlsx(data: bytes, tmp: Path):
    tmp.write_bytes(data)
    ws = openpyxl.load_workbook(tmp, read_only=True).worksheets[0]
    rows, header, section, skip, fin_col = [], None, None, False, None
    for r in ws.iter_rows(values_only=True):
        first = r[0]
        if isinstance(first, str) and all(c is None for c in r[1:]):
            section = first.strip()
            skip = bool(KIDS.search(section) or RELAY.search(section))
            continue
        if first == "Hely.":
            header = [str(c).strip() if c else "" for c in r]
            fin_col = next((h for h in reversed(header) if re.match(r"(cél|finish|idő|eredmény)", h, re.I)), None)
            continue
        if skip or header is None or not any(r):
            continue
        rec = dict(zip(header, r))
        name = clean(rec.get("Név"))
        finish = to_sec(rec.get(fin_col)) if fin_col else None
        if not name or finish is None:
            continue
        sec_l = (section or "").lower()
        sex = "F" if ("női" in sec_l or "noi" in sec_l) else "M" if ("férfi" in sec_l or "ferfi" in sec_l) else None
        segs_cols = [h for h in header if h and h not in META and h != fin_col]
        by = rec.get("Szül.év")
        rows.append({
            "name": name, "birth_year": by if isinstance(by, int) and by > 1900 else None, "sex": sex,
            "sex_rank": rec["Hely."] if isinstance(rec.get("Hely."), int) else None,
            "bib": rec.get("Rsz"), "club": clean(rec.get("Klub")), "license": clean(rec.get("License")),
            "finish": finish, "segs": [to_sec(rec.get(h)) for h in segs_cols],
            "seg_labels": [seg_name(h) for h in segs_cols],
        })
    # kumulált (összesített) részidők felismerése: ha a sorok többségében az
    # értékek nem csökkennek, és összegük jóval nagyobb a célidőnél
    def is_cum(r):
        v = [x for x in r["segs"] if x is not None]
        return len(v) >= 2 and all(b >= a for a, b in zip(v, v[1:])) and v[-1] <= r["finish"] and sum(v) > r["finish"] * 1.3
    if rows and sum(1 for r in rows if is_cum(r)) > len(rows) / 2:
        for r in rows:
            out, prev = [], 0
            for x in r["segs"]:
                if x is None:
                    out.append(None)
                    continue
                out.append(x - prev if x >= prev else None)
                prev = x
            r["segs"] = out
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = CACHE / "_tmp.xlsx"
    catalog = []
    for year, event, series in EVENTS:
        title, ds = distances(event)
        targets = ds or [("", title)]
        for code, label in targets:
            if (series, code) in SKIP_DISTANCE or (event, code) in SKIP_EVENT_DISTANCE \
                    or KIDS.search(label) or RELAY.search(label):
                continue
            params = {"eventid": event, "lang": "hu"}
            if code:
                params["distance"] = code
            data = get("xlsgen.php", params, f"{event}/xls_{code or 'all'}.xlsx", binary=True)
            if len(data) < 500:
                print(f"  ! üres export: {event} {code}")
                continue
            try:
                rows = parse_xlsx(data, tmp)
            except Exception as e:  # pl. hibaoldal XLSX helyett
                print(f"  ! nem olvasható export: {event} {code} ({e.__class__.__name__})")
                continue
            if not rows:
                continue
            # a szakasz-oszlopok közül az általában üreseket elhagyjuk
            labels = rows[0]["seg_labels"]
            keep = [i for i in range(len(labels)) if sum(1 for r in rows if r["segs"][i]) >= max(1, len(rows) // 5)]
            for r in rows:
                r["segs"] = [r["segs"][i] for i in keep]
                del r["seg_labels"]
            name = label if ds else re.sub(r"\s*\b20\d\d\b", "", title).strip(" -–,")
            import unicodedata
            slug = "".join(c for c in unicodedata.normalize("NFKD", (code or name).lower()) if not unicodedata.combining(c))
            key = f"{year}-{series}-{re.sub(r'[^a-z0-9]+', '-', slug).strip('-')}"
            (OUT / f"{key}.json").write_text(json.dumps(
                {"key": key, "year": year, "series": series, "series_name": SERIES[series], "event": event,
                 "event_title": title, "distance": code, "name": name, "seg_labels": [labels[i] for i in keep],
                 "rows": rows}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            catalog.append({"key": key, "year": year, "series": series, "name": name, "n": len(rows),
                            "segs": [labels[i] for i in keep]})
            print(f"{key:45s} {len(rows):5d}  {name}  {[labels[i] for i in keep]}")
    tmp.unlink(missing_ok=True)
    (OUT / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Összesen: {len(catalog)} verseny, {sum(c['n'] for c in catalog)} eredmény")


if __name__ == "__main__":
    main()
