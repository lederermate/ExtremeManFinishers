#!/usr/bin/env python3
"""Összefésüli a forrásokat, és legyártja:
  - supabase/seed.sql        -> a Supabase SQL Editorban lefuttatandó adatbetöltés
  - data/finishers.json      -> tartalék adat a weboldalnak (ha a Supabase nem elérhető)
  - data/match_report.txt    -> a párosítás naplója ellenőrzéshez

Források:
  data/extremetour.json      (scrape_extremetour.py) – 1990-től, név + idő + helyezés
  data/evochip_<év>.json     (import_evochip.py)     – részidők, szül. év, klub, licenc
  data/overrides.json        kézi párosítás: {"<év>": {"<EvoChip név>": <athlete_id> | "new"}}

Két lépés:

A) DÚSÍTÁS – azokban az években, amelyek az extremetour.hu-n is szerepelnek
   (pl. 2022–2025), minden EvoChip sort hozzákötünk a meglévő extremetour
   eredményhez: célidő (±3 mp) + névhasonlóság alapján. Az eredmény így részidőt,
   klubot kap, a versenyző pedig születési évet, nemet és "EvoChip-identitást"
   (az EvoChip által használt névírás + szül. év, licencszám).

B) ÚJ ÉV – azokban az években, amelyek csak az EvoChipen vannak (pl. 2026),
   minden sort versenyzőhöz rendelünk, ebben a sorrendben:
     1. kézi párosítás (overrides.json)
     2. EvoChip-identitás: ugyanaz a név + szül. év egy korábbi EvoChip évből,
        vagy ugyanaz a licencszám
     3. extremetour név: egyértelmű névegyezés (szül. évvel, ha van)
     4. névrészlet: az egyik név a másik része ("Szilágyi Tamás" ⊂ "Szilágyi
        Tamás László") ÉS a születési év egyezik
     5. különben új versenyző (100001-től); ha volt névrokon, "KÉTES" a naplóban
"""
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
NEW_ID_START = 100001
TIME_TOL = 3  # mp – az EvoChip és az extremetour kerekítése eltérhet


def to_sec(t: str) -> int:
    p = [int(x) for x in t.split(":")]
    while len(p) < 3:
        p.insert(0, 0)
    return p[0] * 3600 + p[1] * 60 + p[2]


def name_year(name: str):
    m = re.search(r"\((\d{4})\)\s*$", name)
    return int(m.group(1)) if m else None


def strip_year(name: str) -> str:
    return re.sub(r"\s*\(\d{4}\)\s*$", "", name).strip()


def key(name: str) -> str:
    n = strip_year(name)
    n = re.sub(r"^((dr|prof|ifj|id)\.?\s+)+", "", n.strip(), flags=re.I)
    n = re.sub(r"[\s\-]+", " ", n).strip().casefold()
    return n


def loose_key(name: str) -> str:
    """Ékezet nélküli kulcs."""
    k = unicodedata.normalize("NFKD", key(name))
    return "".join(c for c in k if not unicodedata.combining(c))


def tokens(name: str) -> frozenset:
    return frozenset(t for t in re.split(r"[\s.]+", loose_key(name)) if t)


def name_sim(a: str, b: str) -> float:
    A, B = tokens(a), tokens(b)
    if not A or not B:
        return 0.0
    if A == B:
        return 1.0
    if A <= B or B <= A:
        return 0.8
    inter = len(A & B)
    return 0.5 * inter / max(len(A), len(B))


def sql_str(v):
    if v is None:
        return "null"
    return "'" + str(v).replace("'", "''") + "'"


def sql_num(v):
    return "null" if v is None else str(int(v))


SPLIT_FIELDS = ("swim", "t1", "bike", "t2", "run")


def norm_lic(lic):
    """Magyar licencszám egységes alakban ("L-242583" = "242583"); a külföldi,
    évhez kötött licencek (pl. "2026TZS317") nem stabilak -> None."""
    m = re.fullmatch(r"(?:L-?)?(\d{3,})", str(lic or "").strip())
    return m.group(1) if m else None


def main() -> None:
    et = json.loads((DATA / "extremetour.json").read_text(encoding="utf-8"))
    overrides_path = DATA / "overrides.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else {}

    athletes = {}  # id -> dict
    for aid, name in et["athletes"].items():
        athletes[int(aid)] = {
            "id": int(aid), "name": strip_year(name), "birth_year": name_year(name),
            "sex": None, "source_name": name,
        }

    results = []
    for r in et["results"]:
        results.append({
            "athlete_id": r["athlete_id"], "year": r["year"], "pos": r["pos"],
            "finish": to_sec(r["time"]), "source": "extremetour",
        })
    et_years = {r["year"] for r in results}

    evo = {}
    for f in sorted(DATA.glob("evochip_*.json")):
        ev = json.loads(f.read_text(encoding="utf-8"))
        evo[ev["year"]] = ev["rows"]

    report = []
    # EvoChip-identitások: (névkulcs, szül. év) -> {athlete_id}, licenc -> {athlete_id}
    ident_name = defaultdict(set)
    ident_lic = defaultdict(set)

    def remember(aid, row):
        if row.get("birth_year"):
            ident_name[(loose_key(row["name"]), row["birth_year"])].add(aid)
        lic = norm_lic(row.get("license"))
        if lic:
            ident_lic[lic].add(aid)

    def absorb(a, row):
        if a["birth_year"] is None and row.get("birth_year"):
            a["birth_year"] = row["birth_year"]
        if row.get("sex"):
            a["sex"] = row["sex"]

    # ------------------------------------------------------------------
    # A) DÚSÍTÁS
    # ------------------------------------------------------------------
    for year in sorted(y for y in evo if y in et_years):
        yres = [r for r in results if r["year"] == year]
        free = set(range(len(yres)))
        pairs = []
        for i, row in enumerate(evo[year]):
            for j, r in enumerate(yres):
                dt = abs(r["finish"] - row["finish"])
                if dt > 1800:
                    continue
                sim = name_sim(row["name"], athletes[r["athlete_id"]]["source_name"])
                # pontos idő + bármilyen névátfedés, VAGY hasonló név kis eltéréssel,
                # VAGY azonos név nagyobb eltéréssel (pl. időbüntetés; az extremetour
                # ideje marad a hivatalos)
                if (dt <= TIME_TOL and sim > 0) or (sim >= 0.8 and dt <= 120) or sim == 1.0:
                    pairs.append((-sim, dt, i, j))
        pairs.sort()
        used_rows, linked = set(), 0
        for _, dt, i, j in pairs:
            if i in used_rows or j not in free:
                continue
            used_rows.add(i)
            free.discard(j)
            row, r = evo[year][i], yres[j]
            a = athletes[r["athlete_id"]]
            for k in SPLIT_FIELDS:
                r[k] = row[k]
            r.update(club=row["club"], bib=row["bib"], sex_rank=row["sex_rank"], source="extremetour+evochip")
            absorb(a, row)
            remember(a["id"], row)
            linked += 1
            if key(row["name"]) != key(a["source_name"]):
                report.append(f"DÚSÍTÁS {year} EvoChip „{row['name']}” ({row['birth_year']}) = #{a['id']} {a['source_name']}  [Δ{dt} mp]")
        # maradékok: azonos célidő (±3 mp), de teljesen eltérő név (pl. házassági név,
        # vagy az egyik forrás elírása) – csak a részidőket vesszük át, a személyes
        # adatokat (szül. év, névjegy) nem, mert a személy nem biztos
        for i, row in enumerate(evo[year]):
            if i in used_rows:
                continue
            near = [j for j in free if abs(yres[j]["finish"] - row["finish"]) <= TIME_TOL]
            if len(near) == 1:
                rows_near = [k for k, rr in enumerate(evo[year]) if k not in used_rows
                             and abs(rr["finish"] - yres[near[0]]["finish"]) <= TIME_TOL]
                if rows_near == [i]:
                    j = near[0]
                    used_rows.add(i)
                    free.discard(j)
                    r = yres[j]
                    for k in SPLIT_FIELDS:
                        r[k] = row[k]
                    r.update(club=row["club"], bib=row["bib"], sex_rank=row["sex_rank"], source="extremetour+evochip")
                    linked += 1
                    report.append(f"DÚSÍTÁS {year} CSAK IDŐ: EvoChip „{row['name']}” ({row['birth_year']}) ≈ "
                                  f"#{r['athlete_id']} {athletes[r['athlete_id']]['source_name']} – csak részidők átvéve")
        for i, row in enumerate(evo[year]):
            if i not in used_rows:
                report.append(f"DÚSÍTÁS {year} NINCS PÁR az extremetour listában: {row['name']} {row['finish']}s"
                              f"{'' if row.get('ranked', True) else ' (helyezés nélkül)'}")
        for j in sorted(free):
            r = yres[j]
            report.append(f"DÚSÍTÁS {year} NINCS EvoChip ADAT: #{r['athlete_id']} {athletes[r['athlete_id']]['source_name']}")
        print(f"{year}: {linked}/{len(yres)} extremetour eredmény kapott EvoChip adatot "
              f"({len(evo[year]) - len(used_rows)} EvoChip sor párosítatlan)")

    # ------------------------------------------------------------------
    # DUPLIKÁTUMOK ÖSSZEVONÁSA – az extremetour.hu ugyanazt az embert néha több
    # azonosítón vezeti. Összevonjuk, ha: azonos név (ékezet/titulus nélkül) +
    # azonos születési év + soha nem indultak ugyanabban az évben.
    # ------------------------------------------------------------------
    years_of = defaultdict(set)
    for r in results:
        years_of[r["athlete_id"]].add(r["year"])
    groups = defaultdict(list)
    for a in athletes.values():
        if a["birth_year"] and years_of[a["id"]]:
            groups[(loose_key(a["source_name"]), a["birth_year"])].append(a)
    remap = {}
    for (nm, by), members in groups.items():
        if len(members) < 2:
            continue
        # kanonikus: a legtöbb eredménnyel rendelkező (egyenlőségnél a kisebb azonosító)
        members.sort(key=lambda a: (-len(years_of[a["id"]]), a["id"]))
        canon = members[0]
        for other in members[1:]:
            if years_of[canon["id"]] & years_of[other["id"]]:
                report.append(f"KÉTES  azonos név + szül. év, de egy évben is indultak – külön marad: "
                              f"#{canon['id']} {canon['source_name']} / #{other['id']} {other['source_name']} ({by})")
                continue
            remap[other["id"]] = canon["id"]
            years_of[canon["id"]] |= years_of[other["id"]]
            accents = lambda n: sum(1 for c in n if ord(c) > 127)
            if (canon["name"].isupper() and not other["name"].isupper()) or \
                    (not other["name"].isupper() and accents(other["name"]) > accents(canon["name"])):
                canon["name"] = other["name"]  # csupa nagybetű vagy ékezet nélküli írásmód helyett
            if canon["sex"] is None:
                canon["sex"] = other["sex"]
            report.append(f"ÖSSZEVONÁS #{other['id']} {other['source_name']} {sorted(years_of[other['id']])} "
                          f"-> #{canon['id']} {canon['source_name']} ({by})")
    for r in results:
        r["athlete_id"] = remap.get(r["athlete_id"], r["athlete_id"])
    for idx_map in (ident_name, ident_lic):
        for k, ids in idx_map.items():
            idx_map[k] = {remap.get(i, i) for i in ids}
    for old in remap:
        athletes.pop(old, None)
    print(f"Duplikátumok összevonva: {len(remap)} adatlap")

    # névindexek (a dúsítás után, mert az születési éveket is ad)
    by_key = defaultdict(list)
    for a in athletes.values():
        by_key[key(a["source_name"])].append(a)

    last_year = defaultdict(int)
    first_year = defaultdict(lambda: 9999)
    for r in results:
        last_year[r["athlete_id"]] = max(last_year[r["athlete_id"]], r["year"])
        first_year[r["athlete_id"]] = min(first_year[r["athlete_id"]], r["year"])

    def cand_str(cands):
        return ", ".join(f"#{c['id']} {c['source_name']} ({c['birth_year'] or '?'}, utoljára {last_year[c['id']]})" for c in cands)

    # ------------------------------------------------------------------
    # B) ÚJ ÉVEK
    # ------------------------------------------------------------------
    next_id = NEW_ID_START
    for year in sorted(y for y in evo if y not in et_years):
        ov = overrides.get(str(year), {})
        stats = defaultdict(int)
        # a helyezés nélküli, célidővel rendelkező sorokat is beszámítjuk – az
        # extremetour.hu is így tesz (pl. 2023: Bars Tamás, időbüntetéssel)
        rows = sorted(evo[year], key=lambda r: r["finish"])
        taken = set()       # egy versenyzőhöz évente csak egy eredmény tartozhat
        assign = {}         # sor indexe -> (versenyző | None, módszer)

        def find(row):
            name, by = row["name"], row["birth_year"]
            # 2. EvoChip-identitás: név + szül. év egy korábbi EvoChip évből
            ids = (ident_name.get((loose_key(name), by), set()) if by else set()) - taken
            if len(ids) == 1:
                return athletes[next(iter(ids))], "EvoChip név+év"
            # 3. extremetour név (csak életkor szerint lehetséges jelöltek: aki a
            #    születési éve alapján 16 évesen még nem érhetett célba, kiesik)
            all_cands = by_key.get(key(name), [])
            cands = [c for c in all_cands if c["id"] not in taken
                     and not (by and first_year[c["id"]] < by + 16)]
            exact = [c for c in cands if strip_year(c["source_name"]) == name]
            same_year = [c for c in cands if by and c["birth_year"] == by]
            if len(same_year) == 1:
                return same_year[0], "név+év"
            if len(cands) > 1 and len(exact) == 1 and exact[0]["birth_year"] in (None, by):
                return exact[0], "pontos név"
            if len(cands) == 1 and (cands[0]["birth_year"] == by or
                                    (cands[0]["birth_year"] is None and len(all_cands) == 1)):
                # születési év nélküli jelöltet csak akkor fogadunk el, ha a név
                # egyedi (gyakori névnél ez csak találgatás lenne)
                return cands[0], "név"
            # 4. névrészlet + születési év
            T = tokens(name)
            part = [a for a in athletes.values()
                    if a["id"] < NEW_ID_START and a["id"] not in taken and by and a["birth_year"] == by
                    and len(T & tokens(a["source_name"])) >= 2
                    and (T <= tokens(a["source_name"]) or tokens(a["source_name"]) <= T)]
            if len(part) == 1:
                return part[0], "névrészlet+év"
            return None, "KÉTES" if by_key.get(key(name)) else ""

        # 1. kör: kézi párosítás és licencszám (ezek a legbiztosabbak)
        for i, row in enumerate(rows):
            if row["name"] in ov:
                v = ov[row["name"]]
                assign[i] = (None if v == "new" else athletes[int(v)], "kézi")
            else:
                ids = ident_lic.get(norm_lic(row.get("license")), set()) - taken
                if len(ids) == 1:
                    assign[i] = (athletes[next(iter(ids))], "licenc")
            if i in assign and assign[i][0]:
                taken.add(assign[i][0]["id"])
        # 2. kör: a többiek, idő szerinti sorrendben
        for i, row in enumerate(rows):
            if i not in assign:
                assign[i] = find(row)
                if assign[i][0]:
                    taken.add(assign[i][0]["id"])

        for pos, row in enumerate(rows, start=1):
            name, by = row["name"], row["birth_year"]
            match, how = assign[pos - 1]
            if match is None:
                aid = next_id
                next_id += 1
                athletes[aid] = {"id": aid, "name": name, "birth_year": by, "sex": row["sex"], "source_name": name}
                stats["kézi (új)" if how == "kézi" else ("KÉTES" if how == "KÉTES" else "új")] += 1
                if how == "KÉTES":
                    report.append(f"KÉTES  {year} {name} ({by}) -> új #{aid}; jelöltek: {cand_str(by_key.get(key(name), []))}")
            else:
                aid = match["id"]
                stats[how] += 1
                absorb(match, row)
                if how != "név" or key(name) != key(match["source_name"]):
                    report.append(f"OK     {year} {name} ({by}) -> #{aid} {match['source_name']} [{how}]")
            remember(aid, row)
            results.append({
                "athlete_id": aid, "year": year, "pos": pos, "finish": row["finish"],
                "sex_rank": row["sex_rank"], "club": row["club"], "bib": row["bib"],
                **{k: row[k] for k in SPLIT_FIELDS}, "source": "evochip",
            })
            if not row.get("ranked", True):
                report.append(f"MEGJ.  {year} {name}: célidővel, de az EvoChipen helyezés nélkül – beszámítva")
        print(f"{year}: " + ", ".join(f"{k}: {v}" for k, v in sorted(stats.items())))

    dup = defaultdict(int)
    for r in results:
        dup[(r["athlete_id"], r["year"])] += 1
    bad = [k for k, v in dup.items() if v > 1]
    if bad:
        raise SystemExit(f"Hiba: egy versenyzőhöz egy évben több eredmény került: {bad}")

    # csak azok a versenyzők, akiknek van eredménye
    used = {r["athlete_id"] for r in results}
    athletes = {k: v for k, v in athletes.items() if k in used}

    order = {"KÉTES": 0, "MEGJ.": 1, "ÖSSZ": 2, "OK  ": 3, "DÚSÍ": 4}
    report.sort(key=lambda l: (order.get(l[:5].strip()[:4], 9), l))
    (DATA / "match_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    # ---- tartalék JSON (tömör, oszlopos formátum) ----
    rlist = sorted(results, key=lambda r: (r["year"], r["pos"]))
    fin = {
        "generated": "build_data.py",
        "athletes": [[a["id"], a["name"], a["birth_year"], a["sex"]] for a in sorted(athletes.values(), key=lambda a: a["id"])],
        "results_cols": ["athlete_id", "year", "pos", "finish", "swim", "t1", "bike", "t2", "run", "club"],
        "results": [
            [r["athlete_id"], r["year"], r["pos"], r["finish"], r.get("swim"), r.get("t1"),
             r.get("bike"), r.get("t2"), r.get("run"), r.get("club")]
            for r in rlist
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

    # ---- köztes mérőpontok (data/laps/<év>.json, rajtszám szerint) ----
    # Tömör forma: versenyzőnként [[összidő_mp, helyezés], ...] – a köridő a
    # különbségekből számolható. Kimenet:
    #   data/splits/<év>.json   tartalék a weboldalnak (versenyző-azonosító szerint)
    #   supabase/seed_laps.sql  a Supabase lap_points + result_laps táblákhoz
    by_bib = {(r["year"], r.get("bib")): r["athlete_id"] for r in results if r.get("bib") is not None}
    out_dir = DATA / "splits"
    lap_sql = ["-- Generálva: scripts/build_data.py. Futtatás: Supabase -> SQL Editor -> Run",
               "begin;", "truncate public.lap_points, public.result_laps;"]
    for f in sorted((DATA / "laps").glob("*.json")) if (DATA / "laps").exists() else []:
        lp = json.loads(f.read_text(encoding="utf-8"))
        year = lp["year"]
        compact = {}
        for bib, pts in lp["athletes"].items():
            if (year, int(bib)) in by_bib:  # csak a célba érkezők
                compact[int(bib)] = [[p[0], p[2]] for p in pts]
        ath = {str(by_bib[(year, b)]): v for b, v in compact.items()}
        out_dir.mkdir(exist_ok=True)
        (out_dir / f"{year}.json").write_text(
            json.dumps({"year": year, "points": lp["points"], "athletes": ath}, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")
        lap_sql.append("insert into public.lap_points (year, idx, label, disc, km) values")
        lap_sql.append(",\n".join(f"({year},{i},{sql_str(p['label'])},{sql_str(p['disc'])},{'null' if p['km'] is None else p['km']})"
                                   for i, p in enumerate(lp["points"])) + ";")
        if compact:
            lap_sql.append("insert into public.result_laps (year, bib, laps) values")
            lap_sql.append(",\n".join(f"({year},{b},'{json.dumps(v, separators=(',', ':'))}')" for b, v in sorted(compact.items())) + ";")
        print(f"Köztes mérőpontok {year}: {len(ath)} célba érkező, {len(lp['points'])} mérőpont")
    lap_sql.append("commit;")
    (ROOT / "supabase" / "seed_laps.sql").write_text("\n".join(lap_sql) + "\n", encoding="utf-8")

    print(f"Összesen: {len(athletes)} versenyző, {len(results)} eredmény "
          f"({sum(1 for r in results if r.get('swim') is not None)} részidővel)")
    print("Kimenet: supabase/seed.sql, data/finishers.json, data/match_report.txt")


if __name__ == "__main__":
    main()
