#!/usr/bin/env python3
"""Keresőbarát (SEO) statikus oldalak generálása a templates/page.html sablonból.

Kimenet:
  index.html                          főoldal (egyedi cím/leírás, OG, JSON-LD, évenkénti linkek)
  versenyzo/<id>-<név>/index.html     minden versenyzőnek saját oldal (eredménytáblázat)
  ev/<év>/index.html                  minden évnek saját oldal (teljes eredménylista)
  sitemap.xml                         az összes oldal a keresőknek

A statikus tartalom a HTML-ben van (a Google látja); betöltés után az app.js
ugyanarra az oldalra rajzolja az interaktív nézetet (grafikonok stb.).

Használat: python3 scripts/build_pages.py   (a build_data.py után)
"""
import html
import json
import re
import shutil
import unicodedata
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://lederermate.github.io/ExtremeManFinishers/"
TEMPLATE = (ROOT / "templates" / "page.html").read_text(encoding="utf-8")
OG_IMAGE = SITE + "images/og.jpg"


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "versenyzo"


def fmt(sec) -> str:
    if sec is None:
        return "–"
    sec = int(round(sec))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def median(vals):
    v = sorted(vals)
    n = len(v)
    if not n:
        return None
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def page(*, depth: int, title: str, description: str, canonical: str, content: str, years_html: str,
         jsonld: list, og_type: str = "website") -> str:
    base = "../" * depth
    seo = f"""<title>{esc(title)}</title>
  <meta name="description" content="{esc(description)}">
  <link rel="canonical" href="{esc(canonical)}">
  <meta property="og:type" content="{og_type}">
  <meta property="og:site_name" content="eXtremeMan Nagyatád finisherek">
  <meta property="og:locale" content="hu_HU">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:url" content="{esc(canonical)}">
  <meta property="og:image" content="{OG_IMAGE}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{esc(title)}">
  <meta name="twitter:description" content="{esc(description)}">
  <meta name="twitter:image" content="{OG_IMAGE}">
  {''.join(f'<script type="application/ld+json">{json.dumps(j, ensure_ascii=False)}</script>' for j in jsonld)}"""
    out = re.sub(r"<!--seo:start-->.*?<!--seo:end-->", seo, TEMPLATE, flags=re.S)
    out = out.replace("<!--base-->", f'<base href="{base}">' if depth else "")
    out = re.sub(r"<!--content:start-->.*?<!--content:end-->", content, out, flags=re.S)
    out = re.sub(r"<!--years:start-->.*?<!--years:end-->", years_html, out, flags=re.S)
    return out


def crumbs(*items):
    return {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": u} for i, (n, u) in enumerate(items)],
    }


def main() -> None:
    d = json.loads((ROOT / "data" / "finishers.json").read_text(encoding="utf-8"))
    A = {a[0]: {"id": a[0], "name": a[1], "by": a[2], "sex": a[3], "res": []} for a in d["athletes"]}
    Y = {}
    for aid, year, pos, t, swim, t1, bike, t2, run, club in d["results"]:
        r = {"a": A[aid], "year": year, "pos": pos, "t": t, "swim": swim, "bike": bike, "run": run, "club": club}
        A[aid]["res"].append(r)
        Y.setdefault(year, []).append(r)
    for rs in Y.values():
        rs.sort(key=lambda r: r["pos"])
    years = sorted(Y)
    for a in A.values():
        a["res"].sort(key=lambda r: r["year"])
        a["path"] = f"versenyzo/{a['id']}-{slug(a['name'])}/"

    # további eXtremeMan versenyek (data/other.json, build_data.py)
    od_path = ROOT / "data" / "other.json"
    od = json.loads(od_path.read_text(encoding="utf-8")) if od_path.exists() else {"races": [], "athletes": [], "results": []}
    RACES = [{"key": k, "year": y, "series": sr, "series_name": sn, "name": nm, "segs": sl, "n": n, "best": b, "median": md, "res": []}
             for k, y, sr, sn, nm, sl, n, b, md in od["races"]]
    for aid, name, by, sex in od["athletes"]:
        A[aid] = {"id": aid, "name": name, "by": by, "sex": sex, "res": [], "path": f"versenyzo/{aid}-{slug(name)}/"}
    for a in A.values():
        a["other"] = []
    for ri, aid, pos, sex_rank, t, segs, club in od["results"]:
        x = {"race": RACES[ri], "a": A[aid], "pos": pos, "t": t, "segs": segs, "club": club}
        RACES[ri]["res"].append(x)
        A[aid]["other"].append(x)
    for rc in RACES:
        rc["res"].sort(key=lambda x: x["pos"])
        rc["path"] = f"verseny/{rc['key']}/"
    for a in A.values():
        a["other"].sort(key=lambda x: (-x["race"]["year"], x["race"]["series_name"], x["race"]["name"]))

    years_html = ('<p class="footer-years">Nagyatád, teljes táv, évenként: '
                  + " ".join(f'<a href="ev/{y}/">{y}</a>' for y in reversed(years))
                  + ' · <a href="versenyek/">További eXtremeMan versenyek</a></p>')

    # régi generált oldalak törlése (pl. átnevezett versenyző)
    for sub in ("versenyzo", "ev", "verseny", "versenyek"):
        if (ROOT / sub).exists():
            shutil.rmtree(ROOT / sub)

    urls = [(SITE, "1.0")]
    n_res = len(d["results"])
    best = min((r for rs in Y.values() for r in rs), key=lambda r: r["t"])

    n_fin = sum(1 for a in A.values() if a["res"])  # csak a nagyatádi teljes táv finisherei
    # ---------------- főoldal ----------------
    top = sorted(A.values(), key=lambda a: (-len(a["res"]), a["name"]))[:10]
    content = f"""
    <div class="page-head">
      <h1>eXtremeMan Nagyatád finisherek</h1>
      <p class="lead">Az eXtremeMan Nagyatád teljes távú triatlon (3,8 km úszás, 180 km kerékpár, 42,2 km futás)
        mind a {n_fin} célba érkezője {years[0]} és {years[-1]} között, összesen {n_res} célba érés.
        Pályacsúcs: {fmt(best['t'])} ({esc(best['a']['name'])}, {best['year']}).</p>
    </div>
    <section class="card"><h2>Legtöbbször célba értek</h2><ol class="rank-list">{''.join(
        f'<li><span class="pos">{i + 1}.</span><a class="who" href="{a["path"]}">{esc(a["name"])}</a><span class="val">{len(a["res"])}×</span></li>'
        for i, a in enumerate(top))}</ol></section>"""
    (ROOT / "index.html").write_text(page(
        depth=0,
        title="eXtremeMan Nagyatád finisherek – eredmények 1990 óta",
        description=(f"Az eXtremeMan Nagyatád teljes táv mind a {n_fin} célba érkezője {years[0]}–{years[-1]}: "
                     "eredmények, részidők, helyezések és egyéni trendgrafikonok. Keress rá a nevedre!"),
        canonical=SITE, content=content, years_html=years_html,
        jsonld=[{
            "@context": "https://schema.org", "@type": "WebSite", "name": "eXtremeMan Nagyatád finisherek",
            "url": SITE, "inLanguage": "hu",
            "description": "Az eXtremeMan Nagyatád teljes távú triatlon célba érkezőinek adatbázisa 1990 óta.",
        }, {
            "@context": "https://schema.org", "@type": "Dataset",
            "name": "eXtremeMan Nagyatád teljes táv – célba érkezők és eredmények",
            "description": f"{n_res} célba érés {years[0]} és {years[-1]} között, részidőkkel 2015-től.",
            "url": SITE, "inLanguage": "hu", "temporalCoverage": f"{years[0]}/{years[-1]}",
            "spatialCoverage": "Nagyatád, Magyarország",
            "creditText": "Források: extremetour.hu, EvoChip Timing Team",
        }],
    ), encoding="utf-8")

    # ---------------- évenkénti oldalak ----------------
    for y in years:
        rs = Y[y]
        splits = any(r["swim"] is not None for r in rs)
        med = median([r["t"] for r in rs])
        rookies = sum(1 for r in rs if r["a"]["res"][0]["year"] == y)
        rows = "".join(
            f'<tr><td class="r">{r["pos"]}.</td><td><a href="{r["a"]["path"]}">{esc(r["a"]["name"])}</a></td>'
            + (f'<td class="muted">{esc(r["club"] or "")}</td><td class="r">{fmt(r["swim"])}</td>'
               f'<td class="r">{fmt(r["bike"])}</td><td class="r">{fmt(r["run"])}</td>' if splits else "")
            + f'<td class="r"><b>{fmt(r["t"])}</b></td></tr>'
            for r in rs)
        head = ("<th>Klub</th><th class=\"r\">Úszás</th><th class=\"r\">Kerékpár</th><th class=\"r\">Futás</th>" if splits else "")
        w = rs[0]
        content = f"""
    <div class="page-head">
      <div class="eyebrow"><a href="#/evek">← Évek</a></div>
      <h1>eXtremeMan Nagyatád {y} – eredmények</h1>
      <p class="lead">{len(rs)} célba érkező a teljes távon ({rookies} először). Győztes: {esc(w['a']['name'])} ({fmt(w['t'])}),
        medián idő: {fmt(med)}.</p>
    </div>
    <section class="card"><div class="table-wrap"><table>
      <thead><tr><th class="r">Hely</th><th>Név</th>{head}<th class="r">Célidő</th></tr></thead>
      <tbody>{rows}</tbody></table></div></section>"""
        url = f"{SITE}ev/{y}/"
        out = ROOT / "ev" / str(y) / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page(
            depth=2,
            title=f"eXtremeMan Nagyatád {y} eredmények – teljes táv",
            description=(f"Az eXtremeMan Nagyatád {y} teljes távú eredménylistája: {len(rs)} célba érkező, "
                         f"győztes {w['a']['name']} {fmt(w['t'])}" + (", részidőkkel." if splits else ".")),
            canonical=url, content=content, years_html=years_html,
            jsonld=[crumbs(("Finisherek", SITE), ("Évek", SITE + "#/evek"), (str(y), url))],
        ), encoding="utf-8")
        urls.append((url, "0.6"))

    # ---------------- versenyzői oldalak ----------------
    def other_table(items):
        rows = "".join(
            f'<tr><td>{x["race"]["year"]}</td><td>{esc(x["race"]["series_name"])}</td>'
            f'<td><a href="{x["race"]["path"]}">{esc(x["race"]["name"])}</a></td>'
            f'<td class="r"><b>{fmt(x["t"])}</b></td><td class="r">{x["pos"]}. / {x["race"]["n"]}</td></tr>'
            for x in items)
        return (f'<section class="card"><h2>További eXtremeMan versenyek</h2><div class="table-wrap"><table>'
                f'<thead><tr><th>Év</th><th>Verseny</th><th>Táv</th><th class="r">Célidő</th><th class="r">Helyezés</th></tr></thead>'
                f'<tbody>{rows}</tbody></table></div></section>')

    n_core = n_side = 0
    for a in A.values():
        res, oth = a["res"], a["other"]
        if not res and not oth:
            continue
        url = SITE + a["path"]
        club = next((r["club"] for r in reversed(res) if r["club"]), None) or next((x["club"] for x in oth if x["club"]), None)
        other_txt = ", ".join(f"{x['race']['series_name']} {x['race']['year']}" for x in oth[:4])
        if res:
            n_core += 1
            b = min(res, key=lambda r: r["t"])
            first, last = res[0]["year"], res[-1]["year"]
            span = str(first) if first == last else f"{first} és {last} között"
            splits = any(r["swim"] is not None for r in res)
            rows = "".join(
                f'<tr><td><a href="ev/{r["year"]}/">{r["year"]}</a></td><td class="r"><b>{fmt(r["t"])}</b></td>'
                f'<td class="r">{r["pos"]}. / {len(Y[r["year"]])}</td>'
                + (f'<td class="r">{fmt(r["swim"])}</td><td class="r">{fmt(r["bike"])}</td><td class="r">{fmt(r["run"])}</td>' if splits else "")
                + "</tr>"
                for r in reversed(res))
            head = ('<th class="r">Úszás</th><th class="r">Kerékpár</th><th class="r">Futás</th>' if splits else "")
            lead = " · ".join(x for x in [
                f"Született {a['by']}" if a["by"] else "", esc(club) if club else "",
                f"{len(res)}× célba ért az eXtremeMan Nagyatád teljes távján {span}"] if x)
            content = f"""
    <div class="page-head">
      <div class="eyebrow"><a href="#/">← Finisherek</a></div>
      <h1>{esc(a['name'])}</h1>
      <p class="lead">{lead}. Legjobb ideje {fmt(b['t'])} ({b['year']}, {b['pos']}. hely).</p>
    </div>
    <section class="card"><h2>Nagyatád – teljes táv</h2><div class="table-wrap"><table>
      <thead><tr><th>Év</th><th class="r">Célidő</th><th class="r">Helyezés</th>{head}</tr></thead>
      <tbody>{rows}</tbody></table></div></section>{other_table(oth) if oth else ''}"""
            times = ", ".join(f"{r['year']}: {fmt(r['t'])}" for r in reversed(res[-3:]))
            title = f"{a['name']} – eXtremeMan Nagyatád eredmények"
            desc = (f"{a['name']} {len(res)}× teljesítette az eXtremeMan Nagyatád teljes távját ({span}). "
                    f"Legjobb idő: {fmt(b['t'])} ({b['year']}). Eredmények: {times}."
                    + (f" További versenyek: {other_txt}." if oth else ""))
            crumb = ("Finisherek", SITE)
        else:
            n_side += 1
            ys = [x["race"]["year"] for x in oth]
            span = str(min(ys)) if min(ys) == max(ys) else f"{min(ys)} és {max(ys)} között"
            lead = " · ".join(x for x in [
                f"Született {a['by']}" if a["by"] else "", esc(club) if club else "",
                f"{len(oth)} eXtremeMan verseny {span}"] if x)
            content = f"""
    <div class="page-head">
      <div class="eyebrow"><a href="#/versenyek">← Versenyek</a></div>
      <h1>{esc(a['name'])}</h1>
      <p class="lead">{lead}.</p>
    </div>{other_table(oth)}"""
            title = f"{a['name']} – eXtremeMan eredmények"
            desc = f"{a['name']} eXtremeMan eredményei ({span}): {other_txt}. Idők, helyezések, részidők."
            crumb = ("Versenyek", SITE + "versenyek/")
        out = ROOT / a["path"] / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page(
            depth=2, title=title, description=desc, canonical=url, content=content, years_html=years_html,
            og_type="profile",
            jsonld=[crumbs(crumb, (a["name"], url)),
                    {"@context": "https://schema.org", "@type": "ProfilePage",
                     "mainEntity": {"@type": "Person", "name": a["name"]}, "url": url}],
        ), encoding="utf-8")
        urls.append((url, "0.5"))

    # ---------------- versenyoldalak + Versenyek áttekintő ----------------
    for rc in RACES:
        rows = "".join(
            f'<tr><td class="r">{x["pos"]}.</td><td><a href="{x["a"]["path"]}">{esc(x["a"]["name"])}</a></td>'
            f'<td class="muted">{esc(x["club"] or "")}</td>'
            + "".join(f'<td class="r">{fmt(v)}</td>' for v in x["segs"])
            + f'<td class="r"><b>{fmt(x["t"])}</b></td></tr>'
            for x in rc["res"])
        head = "".join(f'<th class="r">{esc(l)}</th>' for l in rc["segs"])
        w = rc["res"][0] if rc["res"] else None
        title = f"{rc['series_name']} {rc['year']} – {rc['name']} eredmények | eXtremeMan"
        content = f"""
    <div class="page-head">
      <div class="eyebrow"><a href="#/versenyek">← Versenyek</a></div>
      <h1>{esc(rc['series_name'])} {rc['year']}</h1>
      <p class="lead">{esc(rc['name'])} · {rc['n']} célba érkező{f" · győztes: {esc(w['a']['name'])} ({fmt(w['t'])})" if w else ''}.</p>
    </div>
    <section class="card"><div class="table-wrap"><table>
      <thead><tr><th class="r">Hely</th><th>Név</th><th>Klub</th>{head}<th class="r">Célidő</th></tr></thead>
      <tbody>{rows}</tbody></table></div></section>"""
        url = SITE + rc["path"]
        out = ROOT / rc["path"] / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page(
            depth=2, title=title,
            description=(f"eXtremeMan {rc['series_name']} {rc['year']}, {rc['name']}: teljes eredménylista "
                         f"({rc['n']} célba érkező" + (f", győztes {w['a']['name']} {fmt(w['t'])}" if w else "") + "), részidőkkel."),
            canonical=url, content=content, years_html=years_html,
            jsonld=[crumbs(("Versenyek", SITE + "versenyek/"), (f"{rc['series_name']} {rc['year']}", url))],
        ), encoding="utf-8")
        urls.append((url, "0.5"))

    series = {}
    for rc in RACES:
        series.setdefault(rc["series"], {"name": rc["series_name"], "races": []})["races"].append(rc)
    blocks = "".join(
        f'<section class="card"><h2>{esc(sr["name"])}</h2>'
        + "".join(f'<p><b>{y}</b>: ' + ", ".join(f'<a href="{rc["path"]}">{esc(rc["name"])}</a> ({rc["n"]})'
                                              for rc in sr["races"] if rc["year"] == y) + "</p>"
                  for y in sorted({rc["year"] for rc in sr["races"]}, reverse=True))
        + "</section>"
        for sr in sorted(series.values(), key=lambda sr: -len(sr["races"])))
    out = ROOT / "versenyek" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page(
        depth=1, title="Versenyek – eXtremeMan eredmények 2015 óta",
        description=("Az összes eXtremeMan verseny eredménye 2015 óta: Nagyatád többi táva, Kaposvár, Gyékényes, "
                     "Balatonszemes triatlon és duatlon, Tab, Velence, Székesfehérvár, Nágocs."),
        canonical=SITE + "versenyek/",
        content=f"""
    <div class="page-head"><h1>eXtremeMan versenyek</h1>
      <p class="lead">{len(RACES)} verseny, {sum(rc['n'] for rc in RACES)} célba érkezés 2015 óta.</p></div>{blocks}""",
        years_html=years_html, jsonld=[crumbs(("Finisherek", SITE), ("Versenyek", SITE + "versenyek/"))],
    ), encoding="utf-8")
    urls.append((SITE + "versenyek/", "0.7"))

    today = date.today().isoformat()
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f"  <url><loc>{esc(u)}</loc><lastmod>{today}</lastmod><priority>{p}</priority></url>" for u, p in urls]
    sm.append("</urlset>")
    (ROOT / "sitemap.xml").write_text("\n".join(sm) + "\n", encoding="utf-8")
    print(f"Kész: index.html, {len(years)} év-oldal, {n_core} nagyatádi + {n_side} további versenyző-oldal, "
          f"{len(RACES)} versenyoldal, sitemap.xml ({len(urls)} URL)")


if __name__ == "__main__":
    main()
