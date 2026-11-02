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
SIDE_ID_START = 200001  # csak a további versenyeken induló versenyzők
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
DISC_TOTAL = {"swim": 3.8, "bike": 180.0, "run": 42.2}


def drop_out_of_order(pts, med=None):
    """A köztes idők időrendje: ha egy mérőpont ideje kilóg a sorból (pl. a szőnyeg
    egy későbbi körben észlelte a chipet), azt elhagyjuk. A leghosszabb, időben nem
    csökkenő pontsorozat marad meg; egyforma hosszúak közül az, amelyik közelebb van
    a versenyző tempója alapján várható időkhöz (med: a mezőny medián összideje
    pontonként). Visszaad: (új pontlista, elhagyott pontok száma)."""
    import math
    idx = [i for i, p in enumerate(pts) if p and p[0] is not None]
    if len(idx) < 2:
        return pts, 0
    last = idx[-1]
    ratio = pts[last][0] / med[last] if med and med[last] else None

    def cost(i):
        if not ratio or not med or not med[i]:
            return 0.0
        return abs(math.log(pts[i][0] / (med[i] * ratio)))
    best = {i: (1, -cost(i), [i]) for i in idx}
    for a, i in enumerate(idx):
        for j in idx[:a]:
            if pts[j][0] <= pts[i][0]:
                ln, c, seq = best[j]
                cand = (ln + 1, c - cost(i), seq + [i])
                if cand[:2] > best[i][:2]:
                    best[i] = cand
    keep = set(max(best.values(), key=lambda b: b[:2])[2])
    out = [p if (i in keep or not p or p[0] is None) else [None, None, None] for i, p in enumerate(pts)]
    return out, len(idx) - len(keep)


def drop_too_fast(pts, points, med):
    """Hihetetlenül gyors szakasz: a versenyző az előző érvényes ponttól ide 35%-kal
    gyorsabban jutott volna el, mint ami a mezőnyhöz mért saját tempójából (az adott
    szakasz medián ideje × a versenyző szakaszonkénti szorzója) következik. Ilyenkor a
    pont ideje hibás (pl. a szőnyeg szembeirányú áthaladáskor olvasta a chipet)."""
    pts = [list(p) if p else p for p in pts]
    dropped = 0
    for disc in ("swim", "bike", "run"):
        ii = [i for i, q in enumerate(points) if q["disc"] == disc]
        if len(ii) < 2:
            continue
        first, last = ii[0], ii[-1]
        b = first - 1
        start_t = 0 if b < 0 else (pts[b][0] if pts[b] and pts[b][0] is not None else None)
        start_m = 0 if b < 0 else med[b]
        if start_t is None or start_m is None or not pts[last] or pts[last][0] is None or not med[last]:
            continue
        f = (pts[last][0] - start_t) / max(1, med[last] - start_m)  # a versenyző szorzója a mezőnyhöz
        prev_t, prev_m = start_t, start_m
        for i in ii:
            if not pts[i] or pts[i][0] is None or med[i] is None:
                continue
            exp_dt = (med[i] - prev_m) * f
            dt = pts[i][0] - prev_t
            if i != last and exp_dt > 1200 and dt < exp_dt / 1.35:
                pts[i] = [None, None, None]
                dropped += 1
                continue
            prev_t, prev_m = pts[i][0], med[i]
    return pts, dropped


def write_anomalies(athletes, results, race_results, races, lap_flags):
    """Automatikus adatellenőrzés -> data/anomalies.txt (átnézéshez)."""
    out = []
    A = athletes
    nm = lambda aid: A[aid]["name"] if aid in A else f"#{aid}"
    by_ath = defaultdict(list)
    for r in results:
        by_ath[r["athlete_id"]].append(("Nagyatád teljes táv", r["year"], "core", r))
    for r in race_results:
        by_ath[r["athlete_id"]].append((r["race"], r["year"], r["event"], r))
    core_event = {}  # év -> a nagyatádi esemény (a többi nagyatádi táv ugyanazon a hétvégén)
    for r in race_results:
        if r["race"].startswith(f"{r['year']}-nagyatad-") and "aquatlon" not in r["race"]:
            core_event[r["year"]] = r["event"]
    # 1) ugyanaz a rendezvény kétszer
    for aid, items in by_ath.items():
        seen = defaultdict(list)
        for name, year, ev, r in items:
            ev_key = core_event.get(year, f"nagyatad-{year}") if ev == "core" else ev
            seen[(year, ev_key)].append(f"{name}" + (f" [{r['how']}: „{r.get('row_name')}” {r.get('row_by')}]" if r.get("how") else ""))
        for (year, ev), names in seen.items():
            if len(names) > 1:
                out.append(f"KÉT EREDMÉNY EGY RENDEZVÉNYEN  {year}  #{aid} {nm(aid)}: {', '.join(names)}")
    # 2–3) részidők
    for r in results:
        if r.get("swim") is None:
            continue
        parts = [r.get(k) for k in ("swim", "t1", "bike", "t2", "run")]
        if all(v is not None for v in parts) and abs(sum(parts) - r["finish"]) > 600:  # büntetés / korrekció ennél kisebb
            out.append(f"RÉSZIDŐK ÖSSZEGE ≠ CÉLIDŐ  {r['year']}  #{r['athlete_id']} {nm(r['athlete_id'])}: "
                       f"{sum(parts)} mp vs {r['finish']} mp")
        if r["swim"] and r["swim"] < 40 * 60:
            out.append(f"GYANÚS ÚSZÁS  {r['year']}  #{r['athlete_id']} {nm(r['athlete_id'])}: {r['swim'] // 60} perc")
        if r.get("bike") and 180 / (r["bike"] / 3600) > 46:
            out.append(f"GYANÚS KERÉKPÁR  {r['year']}  #{r['athlete_id']} {nm(r['athlete_id'])}: {180 / (r['bike'] / 3600):.1f} km/h")
        if r.get("run") and r["run"] < 2 * 3600 + 20 * 60:
            out.append(f"GYANÚS FUTÁS  {r['year']}  #{r['athlete_id']} {nm(r['athlete_id'])}: {r['run'] // 60} perc")
        for k in ("t1", "t2"):
            if r.get(k) and r[k] > 45 * 60:
                out.append(f"HOSSZÚ DEPÓ ({k.upper()})  {r['year']}  #{r['athlete_id']} {nm(r['athlete_id'])}: {r[k] // 60} perc")
    # 4) életkor
    for aid, items in by_ath.items():
        by = A.get(aid, {}).get("birth_year")
        if not by:
            continue
        for name, year, ev, r in items:
            age = year - by
            if age < 16 or age > 80:
                out.append(f"ÉLETKOR {age}  {year}  #{aid} {nm(aid)} ({by}): {name}")
    # 5) nem-ütközés, 6) eltérő névírás
    for aid, items in by_ath.items():
        sexes = {r.get("row_sex") for _, _, _, r in items if r.get("row_sex")}
        if len(sexes) > 1:
            out.append(f"FÉRFI ÉS NŐI EREDMÉNY IS  #{aid} {nm(aid)}: "
                       + ", ".join(f"{n} {y} ({r.get('row_sex')})" for n, y, _, r in items if r.get("row_sex")))
        base = A[aid]["source_name"] if aid in A else ""
        for name, year, ev, r in items:
            rn = r.get("row_name")
            if rn and base and name_sim(rn, base) == 0:
                out.append(f"ELTÉRŐ NÉV  #{aid} {base}  <-  „{rn}” ({r.get('row_by')}) {name} {year}"
                           + (f" [{r['how']}]" if r.get("how") else ""))
    # 7) nagy helyezés-ugrás a köztes időkben
    for year, bib, a, b, r0, r1 in lap_flags:
        out.append(f"HELYEZÉS-UGRÁS  {year}  rajtszám {bib}: {a} → {b}: {r0}. → {r1}.")
    kinds = defaultdict(int)
    for l in out:
        kinds[re.split(r"\s{2}", l)[0]] += 1
    head = ["# Automatikus adatellenőrzés (build_data.py). Típusonként:"] + [f"#   {k}: {v}" for k, v in sorted(kinds.items())] + [""]
    (DATA / "anomalies.txt").write_text("\n".join(head + sorted(out)) + "\n", encoding="utf-8")
    print("Anomáliák: " + ", ".join(f"{k}: {v}" for k, v in sorted(kinds.items())))


def fix_lap_gaps(points):
    """Ha egy szakasz minden mérőpontja körszámozott ("N. kör", "Kör N"), és a számozásban
    rés van (hiányzó mérőpont), a következő pont távja a kihagyott körökkel együtt értendő."""
    rx = re.compile(r"(\d+)\.\s*k[öo]r|k[öo]r\s*(\d+)", re.I)
    for disc in {p["disc"] for p in points}:
        idx = [i for i, p in enumerate(points) if p["disc"] == disc]
        nums = []
        for i in idx:
            m = rx.search(points[i]["label"])
            nums.append(int(m.group(1) or m.group(2)) if m else None)
        if len(idx) < 2 or None in nums or nums != sorted(nums):
            continue
        prev = 0
        for i, n in zip(idx, nums):
            if n - prev > 1 and points[i]["km"]:
                points[i]["km"] = round(points[i]["km"] * (n - prev), 3)
            prev = n


STD_TOTAL = {"swim": [0.75, 1.5, 1.9, 3.8], "bike": [20, 40, 45, 60, 80, 90, 120, 180],
             "run": [5, 7.5, 10, 21.1, 42.2], "kayak": [10, 20]}


def insert_hidden_points(lp):
    """Rejtett mérőpontok: az EvoChip egyéni oldala néha nem listáz egy mérőpontot (pl. a
    kerékpár célját), de a következő pont köridője (index 1) csak az utolsó, meg nem
    jelenített mérés óta számít (pl. "Depó 2" = 7 perc, miközben 40 perc telt el). Ha ez a
    mezőny többségénél így van, a hiányzó pontot visszaállítjuk (összidő − köridő).
    Csak depó előtt (máshol, pl. a régi kaposvári versenyeken a köridő mást jelent).
    Visszaadja a beszúrt pontok indexét (a km-t később, a normalizálás után töltjük ki)."""
    P, A = lp["points"], lp["athletes"]
    added, i = [], 1
    while i < len(P):
        hid = tot = 0
        for a in A.values():
            if i < len(a) and a[i] and a[i - 1] and a[i][0] is not None and a[i - 1][0] is not None \
                    and a[i][1] is not None:
                tot += 1
                hid += a[i][1] > 0 and a[i][1] < (a[i][0] - a[i - 1][0]) - 30
        if tot >= 3 and hid > tot / 2 and P[i - 1]["disc"] in STD_TOTAL and P[i]["disc"] == "tr":
            prev = P[i - 1]
            name = {"swim": "Úszás", "bike": "Kerékpár", "run": "Futás", "kayak": "Kajak"}[prev["disc"]]
            P.insert(i, {"label": f"{name} (vége)", "disc": prev["disc"], "km": None})
            for a in A.values():
                if i > len(a):
                    continue
                cur = a[i] if i < len(a) else None
                ok = cur and cur[0] is not None and cur[1] and a[i - 1] and a[i - 1][0] is not None \
                    and a[i - 1][0] < cur[0] - cur[1] < cur[0]
                a.insert(i, [cur[0] - cur[1], None, None] if ok else [None, None, None])
            added.append(i)
            i += 1
        i += 1
    return added


def fill_hidden_km(points, athletes, added):
    """A beszúrt pont távja: a szakasz addigi medián tempójával becsülve, majd ha egy
    szokásos össztávhoz (pl. 90 km) közel esik, arra kerekítve."""
    def med_seg(i):
        v = sorted(a[i][0] - a[i - 1][0] for a in athletes.values()
                   if i < len(a) and a[i] and a[i - 1] and a[i][0] is not None and a[i - 1][0] is not None
                   and a[i][0] > a[i - 1][0])
        return v[len(v) // 2] if v else None
    for i in added:
        disc = points[i]["disc"]
        idx = [j for j in range(i) if points[j]["disc"] == disc and points[j]["km"]]
        t_new = med_seg(i)
        km_prev = sum(points[j]["km"] for j in idx)
        t_prev = [med_seg(j) for j in idx if j > 0]
        if not idx or not t_new or None in t_prev or not t_prev:
            continue
        speed = sum(points[j]["km"] for j in idx if j > 0) / sum(t_prev)
        est = speed * t_new
        total = km_prev + est
        snap = [s for s in STD_TOTAL[disc] if abs(s - total) < total * 0.08 and s > km_prev]
        points[i]["km"] = round((min(snap, key=lambda s: abs(s - total)) - km_prev) if snap else est, 2)


def drop_point(lp, i):
    lp["points"].pop(i)
    for a in lp["athletes"].values():
        if i < len(a):
            a.pop(i)


def drop_empty_points(lp):
    """Az a mérőpont, amelyen senkinek sincs ideje, nem kell (pl. Nagyatád 2024 f21: "Futás 5.2 km")."""
    for i in range(len(lp["points"]) - 1, -1, -1):
        if not any(i < len(a) and a[i] and a[i][0] is not None for a in lp["athletes"].values()):
            drop_point(lp, i)


PLAUSIBLE = {"swim": (1.0, 6.5), "bike": (12, 55), "run": (6, 25), "kayak": (3, 16)}  # km/h


def validate_points(lp):
    """Végső ellenőrzés: ha egy szakaszon a mezőny medián sebessége nem lehet valódi (hibás
    táv vagy elcsúszott mérőpont-név), a pontot elhagyjuk; a távja a következő, azonos
    szakaszú pontra kerül (a két mérés közti időt az együtt fedi le). Visszaadja az elhagyottakat."""
    dropped = []
    while True:
        P, worst = lp["points"], None
        for i, p in enumerate(P):
            if p["disc"] not in PLAUSIBLE or not p["km"]:
                continue
            sp = sorted(p["km"] / ((a[i][0] - (a[i - 1][0] if i else 0)) / 3600) for a in lp["athletes"].values()
                        if i < len(a) and a[i] and a[i][0] is not None and (i == 0 or (a[i - 1] and a[i - 1][0] is not None))
                        and a[i][0] > (a[i - 1][0] if i else 0))
            if len(sp) < 3:
                continue
            m = sp[len(sp) // 2]
            lo, hi = PLAUSIBLE[p["disc"]]
            bad = max(lo / m, m / hi)
            if bad > 1 and (worst is None or bad > worst[0]):
                worst = (bad, i)
        if worst is None:
            return dropped
        i = worst[1]
        p = P[i]
        dropped.append(f"{p['label']} ({p['km']} km)")
        if i + 1 < len(P) and P[i + 1]["disc"] == p["disc"] and P[i + 1]["km"]:
            P[i + 1]["km"] = round(P[i + 1]["km"] + p["km"], 3)
        drop_point(lp, i)


# Kézi távjavítások (az EvoChip hibás adata): kulcs -> {mérőpont index: szakasz km}
KM_FIX = {
    "2024-balatonszemes-duatlon-itt": {1: 10.0},  # 3 × 10 km-es kör (ITT30), a 2. kör távja hibásan 3
}
KM_LABEL_RX = re.compile(r"(\d+(?:[.,]\d+)?)\s*km\b", re.I)
KM_BARE_RX = re.compile(r"^[^\d(]*\s(\d+(?:[.,]\d+)?)\s*$")  # pl. "Kerékpár 92"


def normalize_points_generic(points, athletes=None, key=None):
    """Mint a normalize_points, de ismeretlen össztávval (további versenyek). A "km" a
    SZAKASZ hossza legyen:
      1. "Futás 0 kör" = depó (a futás kezdete), nem futószakasz;
      2. ha a mérőpontok nevében km-jelölés van ("Kerékpár 26.5 Km"), az a rajttól (a
         szakasz elejétől) mért táv – ez megbízhatóbb az EvoChip km-adatánál;
      3. különben a növekvő km-sor lehet szakaszhossz vagy összesített táv: azt választjuk,
         amelyiknél a mezőny medián tempója egyenletesebb."""
    for p in points:
        if re.search(r"(?<![\d.])0\.?\s*k[öo]r", p["label"], re.I):
            p["disc"], p["km"] = "tr", None
        # a cél pár méterrel az utolsó kör mérése után (pl. Kaposvár 2017): nem szakasz
        if re.match(r"\*?\s*(cél|finish)", p["label"], re.I) and p["km"] is not None and p["km"] <= 0.3:
            p["disc"], p["km"] = "tr", None
    seg_t = [None] * len(points)
    if athletes:
        for i in range(len(points)):
            v = sorted(a[i][0] - (a[i - 1][0] if i else 0) for a in athletes.values()
                       if i < len(a) and a[i][0] is not None and (i == 0 or a[i - 1][0] is not None))
            v = [x for x in v if x > 0]
            seg_t[i] = v[len(v) // 2] if len(v) >= 3 else None

    def spread(idx, kms):
        sp = [k / seg_t[i] for i, k in zip(idx, kms) if seg_t[i] and k and k > 0]
        if len(sp) < len(idx) or len(sp) < 2:
            return None
        return max(sp) / min(sp)

    for disc in {p["disc"] for p in points} - {"tr", None}:
        idx = [i for i, p in enumerate(points) if p["disc"] == disc]
        lab = []
        for i in idx:
            l = points[i]["label"]
            m = KM_LABEL_RX.search(l)
            v = float(m.group(1).replace(",", ".")) if m else None
            if v is None and disc != "swim" and not re.search(r"k[öo]r", l, re.I):
                m = KM_BARE_RX.match(l)
                v = float(m.group(1).replace(",", ".")) if m else None
                v = v if v and v >= 5 else None
            lab.append(v)
        kms = [points[i]["km"] for i in idx]
        cands = []  # (név, szakaszhosszak) – a legegyenletesebb tempót adó nyer
        known = [v for v in lab if v is not None]
        if known and None not in lab[:-1] and all(b > a for a, b in zip(known, known[1:])) \
                and (len(idx) == 1 or len(known) >= 2):
            prev, by_label = 0.0, []
            for k, v in zip(kms, lab):
                by_label.append(k if v is None else round(v - prev, 3))
                prev = prev if v is None else v
            cands.append(("label", by_label))
        cands.append(("raw", kms))
        if len(kms) > 1 and all(k is not None for k in kms) and all(b > a for a, b in zip(kms, kms[1:])):
            cands.append(("cum", [round(b - a, 3) for a, b in zip([0.0] + kms, kms)]))
        scored = [(spread(idx, c), n, c) for n, c in cands]
        if all(s is not None for s, _, _ in scored):
            best = min(scored, key=lambda x: x[0] - (0.05 if x[1] == "label" else 0))[2]
        elif cands[0][0] == "label":
            best = cands[0][1]
        elif len(cands) > 1 and sum(kms) > kms[-1] * 1.3:
            best = cands[1][1]
        else:
            best = kms
        for i, k in zip(idx, best):
            points[i]["km"] = k
    for i, km in KM_FIX.get(key, {}).items():
        if i < len(points):
            points[i]["km"] = km


def normalize_points(points):
    """A mérőpontok "km" értéke legyen a SZAKASZ hossza. Néhány évben (pl. 2015)
    a rajttól mért összesített táv szerepel, máshol hiányzik – javítjuk."""
    for disc, total in DISC_TOTAL.items():
        idx = [i for i, p in enumerate(points) if p["disc"] == disc]
        if not idx:
            continue
        kms = [points[i]["km"] for i in idx]
        if all(k is None for k in kms):
            for i in idx:  # nincs táv megadva: egyenletes felosztás (közelítés)
                points[i]["km"] = round(total / len(idx), 3)
        elif all(k is not None for k in kms) and len(kms) > 1 and all(b > a for a, b in zip(kms, kms[1:])) \
                and abs(kms[-1] - total) < total * 0.15 and sum(kms) > total * 1.3:
            prev = 0.0
            for i in idx:  # összesített -> szakaszhossz
                cum = points[i]["km"]
                points[i]["km"] = round(cum - prev, 3)
                prev = cum


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

    lic_rejects = []

    def lic_ok(aid, row):
        """A licencszám néha hibás az EvoChipen (pl. két különböző ember ugyanazzal):
        csak akkor fogadjuk el, ha a név is hasonlít, vagy egyezik a születési év."""
        a = athletes[aid]
        sim = name_sim(row["name"], a["source_name"])
        same_by = bool(row.get("birth_year")) and a["birth_year"] == row["birth_year"]
        ok = sim >= 0.5 or (sim > 0 and same_by)
        if not ok:
            lic_rejects.append(f"LICENC? „{row['name']}” ({row.get('birth_year')}) licence {row.get('license')} "
                               f"= #{aid} {a['source_name']} ({a['birth_year']}) – elutasítva, a név (és a szül. év) nem egyezik")
        return ok

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
            r.update(club=row["club"], bib=row["bib"], sex_rank=row["sex_rank"], source="extremetour+evochip",
                     row_name=row["name"], row_sex=row["sex"], row_by=row["birth_year"])
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
                    r.update(club=row["club"], bib=row["bib"], sex_rank=row["sex_rank"], source="extremetour+evochip",
                     row_name=row["name"], row_sex=row["sex"], row_by=row["birth_year"])
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
    # C) TOVÁBBI eXtremeMan VERSENYEK (data/races/*.json, scripts/evochip_races.py)
    #    A 2026-os nagyatádi párosítás ELŐTT, hogy az itt megismert versenyzők
    #    (licenc, név + szül. év) ott is felismerhetők legyenek.
    #    Párosítás: licencszám -> EvoChip név + szül. év -> extremetour név + szül. év
    #    -> különben új versenyző (200001-től).
    # ------------------------------------------------------------------
    side_next = SIDE_ID_START
    races, race_results = [], []
    side_stats = defaultdict(int)
    for f in sorted((DATA / "races").glob("2*.json")) if (DATA / "races").exists() else []:
        rc = json.loads(f.read_text(encoding="utf-8"))
        # kiskorúak kihagyása (nyílt rövid távokon kategória nélkül is indulnak gyerekek):
        # aki a születési éve alapján 16 évesnél fiatalabb volt, nem kerül be
        kids = [r for r in rc["rows"] if r["birth_year"] and rc["year"] - r["birth_year"] < 16]
        side_stats["kiskorú (kihagyva)"] += len(kids)
        rows = sorted((r for r in rc["rows"] if r not in kids), key=lambda r: r["finish"])
        if not rows:
            continue
        taken = set()
        for pos, row in enumerate(rows, start=1):
            by, aid, how = row["birth_year"], None, ""
            lic = norm_lic(row.get("license"))
            ids = {i for i in (ident_lic.get(lic, set()) if lic else set()) - taken if lic_ok(i, row)}
            if len(ids) == 1:
                aid, how = next(iter(ids)), "licenc"
            else:
                ids = (ident_name.get((loose_key(row["name"]), by), set()) if by else set()) - taken
                if len(ids) == 1:
                    aid, how = next(iter(ids)), "név+év"
                else:
                    cands = [c for c in by_key.get(key(row["name"]), []) if c["id"] not in taken and by and c["birth_year"] == by]
                    if len(cands) == 1:
                        aid, how = cands[0]["id"], "extremetour név+év"
            if aid is None:
                aid, how = side_next, "új"
                side_next += 1
                athletes[aid] = {"id": aid, "name": row["name"], "birth_year": by, "sex": row["sex"], "source_name": row["name"]}
                by_key[key(row["name"])].append(athletes[aid])
            else:
                absorb(athletes[aid], row)
            taken.add(aid)
            remember(aid, row)
            side_stats[how] += 1
            race_results.append({"race": rc["key"], "event": rc["event"], "year": rc["year"], "row_name": row["name"],
                                 "row_sex": row["sex"], "row_by": row["birth_year"], "how": how,
                                 "athlete_id": aid, "pos": pos, "sex_rank": row["sex_rank"], "bib": row.get("bib"),
                                 "finish": row["finish"], "segs": row["segs"], "club": row["club"]})
        ts = [r["finish"] for r in rows]
        races.append({"key": rc["key"], "year": rc["year"], "series": rc["series"], "series_name": rc["series_name"],
                      "name": rc["name"], "seg_labels": rc["seg_labels"], "n": len(rows),
                      "best": ts[0] if ts else None, "median": sorted(ts)[len(ts) // 2] if ts else None})
    if races:
        print(f"További versenyek: {len(races)} verseny, {len(race_results)} eredmény; párosítás: "
              + ", ".join(f"{k}: {v}" for k, v in sorted(side_stats.items())))

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
                ids = {i for i in ident_lic.get(norm_lic(row.get("license")), set()) - taken if lic_ok(i, row)}
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
                "row_name": row["name"], "row_sex": row["sex"], "row_by": row["birth_year"],
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

    # csak azok a versenyzők, akiknek van eredménye (nagyatádi teljes táv vagy további verseny)
    core_ids = {r["athlete_id"] for r in results}
    used = core_ids | {r["athlete_id"] for r in race_results}
    athletes = {k: v for k, v in athletes.items() if k in used}

    report.extend(lic_rejects)
    order = {"KÉTES": 0, "LICE": 1, "MEGJ.": 2, "ÖSSZ": 3, "OK  ": 4, "DÚSÍ": 5}
    report.sort(key=lambda l: (order.get(l[:5].strip()[:4], 9), l))
    (DATA / "match_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    # ---- tartalék JSON (tömör, oszlopos formátum) ----
    rlist = sorted(results, key=lambda r: (r["year"], r["pos"]))
    fin = {
        "generated": "build_data.py",
        "athletes": [[a["id"], a["name"], a["birth_year"], a["sex"]]
                     for a in sorted(athletes.values(), key=lambda a: a["id"]) if a["id"] in core_ids],
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
           "truncate public.results, public.athletes restart identity cascade;"]
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

    # ---- további versenyek: data/other.json (tartalék) + supabase/seed_races.sql ----
    ridx = {r["key"]: i for i, r in enumerate(races)}
    other = {
        "races": [[r["key"], r["year"], r["series"], r["series_name"], r["name"], r["seg_labels"], r["n"], r["best"], r["median"]] for r in races],
        "athletes": [[a["id"], a["name"], a["birth_year"], a["sex"]]
                     for a in sorted(athletes.values(), key=lambda a: a["id"]) if a["id"] not in core_ids],
        "results": [[ridx[r["race"]], r["athlete_id"], r["pos"], r["sex_rank"], r["finish"], r["segs"], r["club"]] for r in race_results],
    }
    (DATA / "other.json").write_text(json.dumps(other, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    rs = ["-- Generálva: scripts/build_data.py. Futtatás: Supabase -> SQL Editor -> Run (a seed.sql UTÁN)",
          "begin;", "truncate public.race_results, public.races cascade;"]
    if races:
        rs.append("insert into public.races (key, year, series, series_name, name, seg_labels, n, best_s, median_s) values")
        rs.append(",\n".join(
            f"({sql_str(r['key'])},{r['year']},{sql_str(r['series'])},{sql_str(r['series_name'])},{sql_str(r['name'])},"
            f"{sql_str(json.dumps(r['seg_labels'], ensure_ascii=False))},{r['n']},{sql_num(r['best'])},{sql_num(r['median'])})"
            for r in races) + ";")
    for i in range(0, len(race_results), 1000):
        rs.append("insert into public.race_results (race_key, athlete_id, pos, sex_rank, finish_s, segs, club) values")
        rs.append(",\n".join(
            f"({sql_str(r['race'])},{r['athlete_id']},{r['pos']},{sql_num(r['sex_rank'])},{r['finish']},"
            f"{sql_str(json.dumps(r['segs']))},{sql_str(r['club'])})" for r in race_results[i:i + 1000]) + ";")
    rs.append("commit;")
    (ROOT / "supabase" / "seed_races.sql").write_text("\n".join(rs) + "\n", encoding="utf-8")

    # ---- köztes mérőpontok (data/laps/<év>.json, rajtszám szerint) ----
    # Tömör forma: versenyzőnként [[összidő_mp, helyezés], ...] – a köridő a
    # különbségekből számolható. Kimenet:
    #   data/splits/<év>.json   tartalék a weboldalnak (versenyző-azonosító szerint)
    #   supabase/seed_laps.sql  a Supabase lap_points + result_laps táblákhoz
    by_bib = {(r["year"], r.get("bib")): r["athlete_id"] for r in results if r.get("bib") is not None}
    out_dir = DATA / "splits"
    lap_dropped = defaultdict(int)
    lap_flags = []
    lap_years = []  # évenkénti SQL utasítások (két fájlba osztva, hogy beférjen az SQL Editorba)
    for f in sorted((DATA / "laps").glob("*.json")) if (DATA / "laps").exists() else []:
        lp = json.loads(f.read_text(encoding="utf-8"))
        year = lp["year"]
        normalize_points(lp["points"])
        fix_lap_gaps(lp["points"])
        compact = {}
        # a mezőny medián összideje mérőpontonként (a kilógó idők felismeréséhez)
        med = []
        for i in range(len(lp["points"])):
            v = sorted(a[i][0] for a in lp["athletes"].values() if i < len(a) and a[i][0] is not None)
            med.append(v[len(v) // 2] if v else None)
        for bib, pts in lp["athletes"].items():
            if (year, int(bib)) in by_bib:  # csak a célba érkezők
                clean_pts, dropped = drop_out_of_order(pts, med)
                clean_pts, d2 = drop_too_fast(clean_pts, lp["points"], med)
                dropped += d2
                lap_dropped[year] += dropped
                compact[int(bib)] = [[p[0], p[2]] for p in clean_pts]
                rk = [(i, p[2], p[0]) for i, p in enumerate(clean_pts) if p and p[2] and p[0] is not None]
                field = max((p[2] for a in lp["athletes"].values() for p in a if p and p[2]), default=1)
                for (i0, r0, t0), (i1, r1, t1) in zip(rk, rk[1:]):
                    # rövid (< 30 perces) szakaszon nagy helyezés-változás gyanús
                    if t1 - t0 < 1800 and abs(r1 - r0) > max(40, field * 0.15) \
                            and "tr" not in (lp["points"][i0]["disc"], lp["points"][i1]["disc"]):  # a depóban valós
                        lap_flags.append((year, int(bib), lp["points"][i0]["label"], lp["points"][i1]["label"], r0, r1))
        ath = {str(by_bib[(year, b)]): v for b, v in compact.items()}
        out_dir.mkdir(exist_ok=True)
        (out_dir / f"{year}.json").write_text(
            json.dumps({"year": year, "points": lp["points"], "athletes": ath}, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")
        yl = ["insert into public.lap_points (year, idx, label, disc, km) values",
              ",\n".join(f"({year},{i},{sql_str(p['label'])},{sql_str(p['disc'])},{'null' if p['km'] is None else p['km']})"
                         for i, p in enumerate(lp["points"])) + ";"]
        if compact:
            yl += ["insert into public.result_laps (year, bib, laps) values",
                   ",\n".join(f"({year},{b},'{json.dumps(v, separators=(',', ':'))}')" for b, v in sorted(compact.items())) + ";"]
        lap_years.append((year, yl))
        print(f"Köztes mérőpontok {year}: {len(ath)} célba érkező, {len(lp['points'])} mérőpont"
              + (f", {lap_dropped[year]} időrendből kilógó köztes idő elhagyva" if lap_dropped[year] else ""))
    # részekre osztás (legfeljebb ~650 KB / fájl), hogy beférjen a Supabase SQL Editorba
    parts, cur, size = [], [], 0
    for y, yl in lap_years:
        n = len("\n".join(yl))
        if cur and size + n > 650_000:
            parts.append(cur)
            cur, size = [], 0
        cur.append((y, yl))
        size += n
    if cur:
        parts.append(cur)
    for old in (ROOT / "supabase").glob("seed_laps*.sql"):
        old.unlink()
    for k, part in enumerate(parts, start=1):
        ys = [y for y, _ in part]
        fname = "seed_laps.sql" if k == 1 else f"seed_laps_{k}.sql"
        body = [f"-- Generálva: scripts/build_data.py. Köridők {ys[0]}–{ys[-1]} ({k}/{len(parts)}. rész).",
                f"-- Futtatás: Supabase -> SQL Editor -> Run, a részek sorrendjében (seed_laps.sql, seed_laps_2.sql, ...)",
                "begin;"]
        body.append("truncate public.lap_points, public.result_laps;" if k == 1 else
                    f"delete from public.lap_points where year between {ys[0]} and {ys[-1]}; "
                    f"delete from public.result_laps where year between {ys[0]} and {ys[-1]};")
        for _, yl in part:
            body += yl
        body.append("commit;")
        (ROOT / "supabase" / fname).write_text("\n".join(body) + "\n", encoding="utf-8")

    # ---- további versenyek köztes mérőpontjai (data/laps_other/<kulcs>.json) ----
    rr_by_bib = defaultdict(dict)
    for r in race_results:
        if r.get("bib") is not None and str(r["bib"]).isdigit():
            rr_by_bib[r["race"]][int(r["bib"])] = r["athlete_id"]
    other_dir = DATA / "splits_other"
    other_dir.mkdir(exist_ok=True)
    for old in other_dir.glob("*.json"):
        old.unlink()
    race_lap_sql, n_other = [], 0
    have, hidden_log = set(), []
    for f in sorted((DATA / "laps_other").glob("*.json")) if (DATA / "laps_other").exists() else []:
        lp = json.loads(f.read_text(encoding="utf-8"))
        rkey = lp["key"]
        if rkey not in rr_by_bib or not lp["points"]:
            continue
        drop_empty_points(lp)
        added = insert_hidden_points(lp)
        normalize_points_generic(lp["points"], lp["athletes"], rkey)
        fill_hidden_km(lp["points"], lp["athletes"], added)
        if added:
            hidden_log.append(f"{rkey}: " + ", ".join(f"{lp['points'][i]['label']} {lp['points'][i]['km']} km" for i in added))
        fix_lap_gaps(lp["points"])
        bad_pts = validate_points(lp)
        if bad_pts:
            hidden_log.append(f"{rkey}: elhagyva (irreális tempó): " + ", ".join(bad_pts))
        if not lp["points"]:
            continue
        med = []
        for i in range(len(lp["points"])):
            v = sorted(a[i][0] for a in lp["athletes"].values() if i < len(a) and a[i][0] is not None)
            med.append(v[len(v) // 2] if v else None)
        ath = {}
        for bib, pts in lp["athletes"].items():
            aid = rr_by_bib[rkey].get(int(bib))
            if aid is None:
                continue  # pl. kiskorú vagy nem célba érkező
            clean_pts, _ = drop_out_of_order(pts, med)
            clean_pts, _ = drop_too_fast(clean_pts, lp["points"], med)
            ath[aid] = [[p[0], p[2]] for p in clean_pts]
        if not ath:
            continue
        have.add(rkey)
        n_other += len(ath)
        (other_dir / f"{rkey}.json").write_text(json.dumps(
            {"key": rkey, "points": lp["points"], "athletes": {str(k): v for k, v in ath.items()}},
            ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        race_lap_sql.append([
            "insert into public.race_lap_points (race_key, idx, label, disc, km) values",
            ",\n".join(f"({sql_str(rkey)},{i},{sql_str(q['label'])},{sql_str(q['disc'] or 'tr')},{'null' if q['km'] is None else q['km']})"
                       for i, q in enumerate(lp["points"])) + ";",
            "insert into public.race_result_laps (race_key, athlete_id, laps) values",
            ",\n".join(f"({sql_str(rkey)},{aid},'{json.dumps(v, separators=(',', ':'))}')" for aid, v in sorted(ath.items())) + ";"])
    # részekre osztva (~650 KB / fájl)
    for old in (ROOT / "supabase").glob("seed_race_laps*.sql"):
        old.unlink()
    parts, cur, size = [], [], 0
    for blk in race_lap_sql:
        n = len("\n".join(blk))
        if cur and size + n > 650_000:
            parts.append(cur)
            cur, size = [], 0
        cur.append(blk)
        size += n
    if cur or not parts:
        parts.append(cur)
    for k, part in enumerate(parts, start=1):
        fname = "seed_race_laps.sql" if k == 1 else f"seed_race_laps_{k}.sql"
        body = [f"-- Generálva: scripts/build_data.py. További versenyek köztes mérőpontjai ({k}/{len(parts)}. rész).",
                "begin;"]
        if k == 1:
            body.append("truncate public.race_lap_points, public.race_result_laps;")
        for blk in part:
            body += blk
        body.append("commit;")
        (ROOT / "supabase" / fname).write_text("\n".join(body) + "\n", encoding="utf-8")
    print(f"További versenyek köztes mérőpontjai: {len(have)} verseny, {n_other} versenyző")
    print(f"Mérőpont-javítások (data/hidden_points.txt): {len(hidden_log)}")
    (DATA / "hidden_points.txt").write_text("\n".join(hidden_log) + "\n", encoding="utf-8")
    # a versenylistában jelöljük, melyikhez van köridő
    oth = json.loads((DATA / "other.json").read_text(encoding="utf-8"))
    for rc in oth["races"]:
        if len(rc) < 10:
            rc.append(False)
        rc[9] = rc[0] in have
    (DATA / "other.json").write_text(json.dumps(oth, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    rs_path = ROOT / "supabase" / "seed_races.sql"
    rs_txt = rs_path.read_text(encoding="utf-8").replace("\ncommit;\n",
        "\nupdate public.races set has_laps = (key in (" + (",".join(sql_str(k) for k in sorted(have)) or "''") + "));\ncommit;\n")
    rs_path.write_text(rs_txt, encoding="utf-8")

    write_anomalies(athletes, results, race_results, races, lap_flags)
    print(f"Összesen: {len(athletes)} versenyző, {len(results)} eredmény "
          f"({sum(1 for r in results if r.get('swim') is not None)} részidővel)")
    print("Kimenet: supabase/seed.sql, data/finishers.json, data/match_report.txt")


if __name__ == "__main__":
    main()
