#!/usr/bin/env python3
"""Az EvoChip XLSX exportjából kiszedi a teljes táv EGYÉNI célba érkezőit.

Az XLSX letöltése (példa, 2026):
  https://www.evochip.hu/results/xlsgen.php?eventid=Nagyatad26VIn&lang=hu&distance=xman

Használat:
  python3 scripts/import_evochip.py sources/evochip/Nagyatad26VIn_xman.xlsx 2026

Kimenet: data/evochip_<év>.json
Csak a "Férfi Abszolút" és "Női Abszolút" szakaszokat veszi, a váltókat nem,
és csak a célidővel rendelkező sorokat (DNF kimarad). A célidővel, de helyezés
nélkül szereplő sorok "ranked": false jelölést kapnak (lehet kizárás vagy
szintidőn túli érkezés – a build_data.py dönt róluk).
"""
import json
import re
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
SECTIONS = {"férfi abszolút": "M", "női abszolút": "F"}


def to_sec(v):
    if v is None:
        return None
    s = str(v).strip()
    if not re.fullmatch(r"\d{1,2}(:\d{1,2}){1,2}", s):
        return None
    parts = [int(x) for x in s.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, sec = parts
    return h * 3600 + m * 60 + sec


def clean(v):
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def main(path: str, year: int) -> None:
    ws = openpyxl.load_workbook(path, read_only=True).worksheets[0]
    sex = None
    header = None
    rows, skipped = [], []
    for r in ws.iter_rows(values_only=True):
        first = r[0]
        if isinstance(first, str) and all(c is None for c in r[1:]):
            sex = SECTIONS.get(first.strip().lower())  # None = váltó / egyéb -> kihagyjuk
            continue
        if first == "Hely.":
            header = [str(c).strip() if c else "" for c in r]
            continue
        if sex is None or header is None or not any(r):
            continue
        rec = dict(zip(header, r))
        finish = to_sec(rec.get("Cél idő"))
        name = clean(rec.get("Név"))
        ranked = isinstance(rec.get("Hely."), int)
        if finish is None:
            skipped.append((name, rec.get("Cél idő")))
            continue
        if not ranked:
            print(f"  ! célidővel, de helyezés nélkül (megtartva, ranked=false): {name} {rec.get('Cél idő')}")
        by = rec.get("Szül.év")
        rows.append({
            "name": name,
            "birth_year": by if isinstance(by, int) and by > 1900 else None,
            "sex": sex,
            "sex_rank": rec["Hely."] if ranked else None,
            "ranked": ranked,
            "bib": rec.get("Rsz"),
            "club": clean(rec.get("Klub")),
            "country": clean(rec.get("Ország")),
            "city": clean(rec.get("Város")),
            "license": clean(rec.get("License")),
            "swim": to_sec(rec.get("Úszás")),
            "t1": to_sec(rec.get("Depó 1")),
            "bike": to_sec(rec.get("Bike")),
            "t2": to_sec(rec.get("Depó 2")),
            "run": to_sec(rec.get("Futás")),
            "finish": finish,
        })

    out = ROOT / "data" / f"evochip_{year}.json"
    out.write_text(json.dumps({"year": year, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{year}: {len(rows)} egyéni célba érkező -> {out.relative_to(ROOT)}")
    print(f"Kihagyva (nem ért célba): {len(skipped)}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], int(sys.argv[2]))
