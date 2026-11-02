#!/usr/bin/env python3
"""A böngészőnek szánt, tömör adatfájlok előállítása (a build_data.py kimenetéből).

Bemenet:  data/finishers.json, data/other.json  (ezekből készül a Supabase seed is – változatlanok)
Kimenet:
  data/finishers.min.json   a nagyatádi teljes táv, évenkénti oszlopos formában:
      {"v": 2, "athletes": [[id, név, szül.év, nem], ...], "clubs": [klubnév, ...],
       "years": {"1990": {"a": [versenyző-id, ...],          # helyezés szerinti sorrendben (helyezés = index + 1)
                          "t": [célidő-különbség, ...],      # az előző célidőhöz képest (az első: abszolút), mp
                          "s"/"t1"/"b"/"t2"/"r": [...],      # úszás, depó 1, kerékpár, depó 2, futás (ha van)
                          "c": [klub-index vagy -1, ...]}}}  # (ha van)
  data/other/index.json     a további versenyek listája + versenyzőnként a versenyek indexe:
      {"races": [ugyanaz, mint az other.json-ban], "ath": [[versenyző-id, verseny-index, ...], ...]}
  data/other/<kulcs>.json   egy verseny eredményei + a csak itt szereplő versenyzők adatai:
      {"res": [[id, hely, nemenkénti hely, idő, [szakaszok], klub], ...], "people": [[id, név, szül.év, nem], ...]}

Így a főoldal kb. fele akkora adatot tölt le, a versenyzői oldal pedig csak azoknak a
versenyeknek a fájlját, amelyeken az illető indult.

Használat: python3 scripts/build_static_data.py   (a build_data.py a végén magától futtatja)
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def dump(path: Path, obj) -> int:
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    path.write_text(txt, encoding="utf-8")
    return len(txt.encode("utf-8"))


def finishers() -> int:
    d = json.loads((DATA / "finishers.json").read_text(encoding="utf-8"))
    cols = d.get("results_cols") or ["athlete_id", "year", "pos", "finish", "swim", "t1", "bike", "t2", "run", "club"]
    assert cols[:4] == ["athlete_id", "year", "pos", "finish"], cols
    by_year = {}
    for r in d["results"]:
        by_year.setdefault(r[1], []).append(r)
    clubs = sorted({r[9] for r in d["results"] if r[9]})
    ci = {c: i for i, c in enumerate(clubs)}
    years = {}
    for y, rs in sorted(by_year.items()):
        rs.sort(key=lambda r: (r[2] if r[2] is not None else 10 ** 9, r[3]))
        # a helyezés az indexből adódik – ha nem így van, a formátum nem használható
        assert all(r[2] == i + 1 for i, r in enumerate(rs)), f"{y}: a helyezések nem 1..n"
        t = [r[3] for r in rs]
        col = {"a": [r[0] for r in rs], "t": [t[0]] + [t[i] - t[i - 1] for i in range(1, len(t))]}
        for k, i in (("s", 4), ("t1", 5), ("b", 6), ("t2", 7), ("r", 8)):
            v = [r[i] for r in rs]
            if any(x is not None for x in v):
                col[k] = v
        if any(r[9] for r in rs):
            col["c"] = [ci[r[9]] if r[9] else -1 for r in rs]
        years[str(y)] = col
    return dump(DATA / "finishers.min.json", {"v": 2, "athletes": d["athletes"], "clubs": clubs, "years": years})


def other() -> tuple[int, int]:
    p = DATA / "other.json"
    if not p.exists():
        return 0, 0
    d = json.loads(p.read_text(encoding="utf-8"))
    out = DATA / "other"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    people = {a[0]: a for a in d["athletes"]}
    per_race = [[] for _ in d["races"]]
    ath = {}
    for row in d["results"]:
        ri, aid = row[0], row[1]
        per_race[ri].append(row[1:])
        ath.setdefault(aid, []).append(ri)
    size = 0
    for race, rows in zip(d["races"], per_race):
        rows.sort(key=lambda r: r[1])
        ppl = [people[r[0]] for r in rows if r[0] in people]
        size += dump(out / f"{race[0]}.json", {"res": rows, "people": ppl})
    idx = dump(out / "index.json", {"races": d["races"], "ath": [[aid, *sorted(set(ris))] for aid, ris in sorted(ath.items())]})
    return idx, len(d["races"])


def main() -> None:
    n_fin = finishers()
    n_idx, n_races = other()
    print(f"data/finishers.min.json ({n_fin // 1024} KB), data/other/index.json ({n_idx // 1024} KB) + {n_races} versenyfájl")


if __name__ == "__main__":
    main()
