#!/usr/bin/env python3
"""Összefésüli a forrásokat, és legyártja:
  - supabase/seed.sql        -> a Supabase SQL Editorban lefuttatandó adatbetöltés
  - data/finishers.json      -> tartalék adat a weboldalnak (ha a Supabase nem elérhető)
  - data/match_report.txt    -> a névpárosítás naplója ellenőrzéshez

Források:
  data/extremetour.json      (scrape_extremetour.py)
  data/evochip_<év>.json     (import_evochip.py)
  data/overrides.json        (kézi párosítás: {"<év>": {"<név>": <athlete_id> | "new"}})

Párosítás (EvoChip név -> extremetour versenyző):
  1. a nevet normalizáljuk (kisbetű, felesleges szóköz, dr./prof. le, "(1969)" le)
  2. ha egy jelölt van -> ő az (kivéve, ha a névben lévő évszám mást mond)
  3. ha több jelölt van -> akinek a teljes neve (titulussal) pontosan egyezik,
     vagy akinek a nevében lévő születési év egyezik
  4. különben új versenyző (100001-től), és bekerül a naplóba "KÉTES" jelöléssel
"""
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
NEW_ID_START = 100001


def to_sec(t: str) -> int:
    p = [int(x) for x in t.split(":")]
    while len(p) < 3:
        p.insert(0, 0)
    return p[0] * 3600 + p[1] * 60 + p[2]


def name_year(name: str):
    m = re.search(r"\((\d{4})\)\s*$", name)
    return int(m.group(1)) if m else None


def key(name: str) -> str:
    n = re.sub(r"\(\d{4}\)\s*$", "", name)
    n = re.sub(r"^(dr\.?|prof\.?|ifj\.?|id\.?)\s+", "", n.strip(), flags=re.I)
    n = re.sub(r"[\s\-]+", " ", n).strip().casefold()
    return n


def loose_key(name: str) -> str:
    """Ékezet nélküli kulcs, csak a napló javaslataihoz."""
    k = unicodedata.normalize("NFKD", key(name))
    return "".join(c for c in k if not unicodedata.combining(c))


def sql_str(v):
    if v is None:
        return "null"
    return "'" + str(v).replace("'", "''") + "'"


def sql_num(v):
    return "null" if v is None else str(int(v))


def main() -> None:
    et = json.loads((DATA / "extremetour.json").read_text(encoding="utf-8"))
    overrides_path = DATA / "overrides.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else {}

    athletes = {}  # id -> dict
    for aid, name in et["athletes"].items():
        athletes[int(aid)] = {
            "id": int(aid),
            "name": re.sub(r"\s*\(\d{4}\)\s*$", "", name),
            "birth_year": name_year(name),
            "sex": None,
            "source_name": name,
        }

    results = []  # dicts
    for r in et["results"]:
        results.append({
            "athlete_id": r["athlete_id"], "year": r["year"], "pos": r["pos"],
            "finish": to_sec(r["time"]), "source": "extremetour",
        })

    by_key = defaultdict(list)
    by_loose = defaultdict(list)
    for a in athletes.values():
        by_key[key(a["source_name"])].append(a)
        by_loose[loose_key(a["source_name"])].append(a)

    last_year = defaultdict(int)
    for r in results:
        last_year[r["athlete_id"]] = max(last_year[r["athlete_id"]], r["year"])

    report = []
    next_id = NEW_ID_START
    for f in sorted(DATA.glob("evochip_*.json")):
        ev = json.loads(f.read_text(encoding="utf-8"))
        year = ev["year"]
        ov = overrides.get(str(year), {})
        if any(r["year"] == year for r in results):
            raise SystemExit(f"{year} már szerepel az extremetour adatokban – ütközés!")
        stats = defaultdict(int)
        # abszolút helyezés: férfi + női együtt, idő szerint
        rows = sorted(ev["rows"], key=lambda r: r["finish"])
        for pos, row in enumerate(rows, start=1):
            name = row["name"]
            match = None
            how = ""
            if name in ov:
                match = None if ov[name] == "new" else athletes[int(ov[name])]
                how = "kézi"
            else:
                cands = by_key.get(key(name), [])
                exact = [c for c in cands if re.sub(r"\s*\(\d{4}\)\s*$", "", c["source_name"]) == name]
                if len(cands) > 1 and len(exact) == 1 and exact[0]["birth_year"] in (None, row["birth_year"]):
                    match, how = exact[0], "pontos név"
                elif row["birth_year"]:
                    same_year = [c for c in cands if c["birth_year"] == row["birth_year"]]
                    no_year = [c for c in cands if c["birth_year"] is None]
                    if len(same_year) == 1:
                        match, how = same_year[0], "név+év"
                    elif len(cands) == 1 and cands[0]["birth_year"] is None:
                        match, how = cands[0], "név"
                    elif not same_year and len(no_year) == 1 and len(cands) > 1:
                        how = "KÉTES"
                    elif cands:
                        how = "KÉTES"
                elif len(cands) == 1:
                    match, how = cands[0], "név"
                elif cands:
                    how = "KÉTES"

            if match is None:
                aid = next_id
                next_id += 1
                athletes[aid] = {"id": aid, "name": name, "birth_year": row["birth_year"],
                                 "sex": row["sex"], "source_name": name}
                status = how if how in ("KÉTES", "kézi") else "új"
                stats[status if status != "kézi" else "kézi (új)"] += 1
                if how == "KÉTES":
                    cands = by_key.get(key(name), [])
                    report.append(
                        f"KÉTES  {year} {name} ({row['birth_year']}) -> új #{aid}; jelöltek: "
                        + ", ".join(f"#{c['id']} {c['source_name']} (utoljára {last_year[c['id']]})" for c in cands)
                    )
                else:
                    loose = [c for c in by_loose.get(loose_key(name), []) if c["id"] < NEW_ID_START]
                    if loose:
                        report.append(
                            f"HASONLÓ {year} {name} -> új #{aid}; ékezet nélkül egyezik: "
                            + ", ".join(f"#{c['id']} {c['source_name']}" for c in loose)
                        )
            else:
                aid = match["id"]
                stats[how] += 1
                if match["birth_year"] is None and row["birth_year"]:
                    match["birth_year"] = row["birth_year"]
                if row["sex"]:
                    match["sex"] = row["sex"]
                report.append(f"OK     {year} {name} -> #{aid} {match['source_name']} [{how}]")

            results.append({
                "athlete_id": aid, "year": year, "pos": pos, "finish": row["finish"],
                "sex_rank": row["sex_rank"], "club": row["club"], "bib": row["bib"],
                "swim": row["swim"], "t1": row["t1"], "bike": row["bike"],
                "t2": row["t2"], "run": row["run"], "source": "evochip",
            })
        print(f"{year}: " + ", ".join(f"{k}: {v}" for k, v in sorted(stats.items())))

    # csak azok a versenyzők, akiknek van eredménye
    used = {r["athlete_id"] for r in results}
    athletes = {k: v for k, v in athletes.items() if k in used}

    (DATA / "match_report.txt").write_text("\n".join(sorted(report)) + "\n", encoding="utf-8")

    # ---- tartalék JSON (tömör, oszlopos formátum) ----
    fin = {
        "generated": "build_data.py",
        "athletes": [[a["id"], a["name"], a["birth_year"], a["sex"]] for a in sorted(athletes.values(), key=lambda a: a["id"])],
        "results_cols": ["athlete_id", "year", "pos", "finish", "swim", "t1", "bike", "t2", "run", "club"],
        "results": [
            [r["athlete_id"], r["year"], r["pos"], r["finish"], r.get("swim"), r.get("t1"),
             r.get("bike"), r.get("t2"), r.get("run"), r.get("club")]
            for r in sorted(results, key=lambda r: (r["year"], r["pos"]))
        ],
    }
    (DATA / "finishers.json").write_text(json.dumps(fin, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # ---- seed.sql ----
    out = ["-- Generálva: scripts/build_data.py. NE szerkeszd kézzel, futtasd újra a szkriptet.",
           "-- Futtatás: Supabase -> SQL Editor -> New query -> beillesztés -> Run",
           "begin;",
           "truncate public.results, public.athletes restart identity;"]
    alist = sorted(athletes.values(), key=lambda a: a["id"])
    for i in range(0, len(alist), 1000):
        out.append("insert into public.athletes (id, name, birth_year, sex) values")
        out.append(",\n".join(
            f"({a['id']},{sql_str(a['name'])},{sql_num(a['birth_year'])},{sql_str(a['sex'])})"
            for a in alist[i:i + 1000]) + ";")
    rlist = sorted(results, key=lambda r: (r["year"], r["pos"]))
    # extremetour sorok: csak idő + helyezés (tömör forma), source utólag
    short = [r for r in rlist if r["source"] == "extremetour"]
    for i in range(0, len(short), 2000):
        out.append("insert into public.results (athlete_id, year, pos, finish_s) values")
        out.append(",\n".join(f"({r['athlete_id']},{r['year']},{r['pos']},{r['finish']})" for r in short[i:i + 2000]) + ";")
    out.append("update public.results set source = 'extremetour' where source is null;")
    full = [r for r in rlist if r["source"] != "extremetour"]
    for i in range(0, len(full), 1000):
        out.append("insert into public.results (athlete_id, year, pos, finish_s, swim_s, t1_s, bike_s, t2_s, run_s, sex_rank, bib, club, source) values")
        out.append(",\n".join(
            f"({r['athlete_id']},{r['year']},{r['pos']},{r['finish']},{sql_num(r.get('swim'))},{sql_num(r.get('t1'))},"
            f"{sql_num(r.get('bike'))},{sql_num(r.get('t2'))},{sql_num(r.get('run'))},{sql_num(r.get('sex_rank'))},"
            f"{sql_num(r.get('bib'))},{sql_str(r.get('club'))},{sql_str(r['source'])})"
            for r in full[i:i + 1000]) + ";")
    out.append("commit;")
    (ROOT / "supabase" / "seed.sql").write_text("\n".join(out) + "\n", encoding="utf-8")

    print(f"Összesen: {len(athletes)} versenyző, {len(results)} eredmény")
    print("Kimenet: supabase/seed.sql, data/finishers.json, data/match_report.txt")


if __name__ == "__main__":
    main()
