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


def huint(n: int) -> str:
    """Mint az app.js-ben az Intl.NumberFormat('hu-HU'): 10 000-től nem törő szóközös ezres tagolás."""
    return f"{n:,}".replace(",", "\u00a0") if n >= 10000 else str(n)


def fit(*parts: str, limit: int = 158) -> str:
    """A meta description részeinek összefűzése, amíg beférnek (a Google kb. 155–160 karakternél vág)."""
    out = parts[0]
    for x in parts[1:]:
        if x and len(out) + 1 + len(x) <= limit:
            out += " " + x
    return out


def hero(*, img: str, pos: str, eyebrow: str, title: str, lead: str = "", stats=(), compact: bool = False) -> str:
    """Fejlécfotó – PONTOSAN az app.js setHero() jelölése, hogy betöltéskor ne ugorjon el a tartalom."""
    st = ("<div class=\"hero-stats\">" + "".join(f"<div><b>{v}</b><span>{l}</span></div>" for v, l in stats) + "</div>") if stats else ""
    return (f'<section class="hero{" compact" if compact else ""}" data-img="{img}">'
            f'<div class="hero-bg" style="background-image:url(images/{img});background-position:{pos}"></div>'
            f'<div class="hero-in"><h1 class="hero-h1"><span class="hero-eyebrow">{eyebrow}</span> <span class="hero-title">{title}</span></h1>'
            + (f'<p class="hero-lead">{lead}</p>' if lead else "") + st + '</div>'
            '<div class="hero-credit">Fotó: <a href="https://www.extrememan.hu/" target="_blank" rel="noopener">extrememan.hu</a></div>'
            '</section>')


def page(*, depth: int, title: str, description: str, canonical: str, content: str, years_html: str,
         jsonld: list, og_type: str = "website", hero_html: str = "") -> str:
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
    # a <base> minden oldalon a gyökérre mutat (a főoldalon is), így a relatív linkek
    # a History API-s navigáció után is jó helyre vezetnek
    out = out.replace("<!--base-->", f'<base href="{base or "./"}">')
    out = re.sub(r"<!--content:start-->.*?<!--content:end-->", content, out, flags=re.S)
    out = re.sub(r"<!--years:start-->.*?<!--years:end-->", years_html, out, flags=re.S)
    if hero_html:
        out = out.replace('<div id="hero"></div>', f'<div id="hero">{hero_html}</div>')
        # a fejlécfotó a legnagyobb elem (LCP) – minél korábban töltődjön
        img = re.search(r"images/([\w.-]+\.jpg)", hero_html).group(1)
        out = out.replace('<link rel="stylesheet" href="style.css">',
                          f'<link rel="preload" href="images/{img}" as="image" fetchpriority="high">\n  <link rel="stylesheet" href="style.css">')
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
             for k, y, sr, sn, nm, sl, n, b, md, *_ in od["races"]]
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
    for sub in ("versenyzo", "ev", "verseny", "versenyek", "evek", "rekordok"):
        if (ROOT / sub).exists():
            shutil.rmtree(ROOT / sub)

    urls = [(SITE, "1.0")]
    n_res = len(d["results"])
    best = min((r for rs in Y.values() for r in rs), key=lambda r: r["t"])

    n_fin = sum(1 for a in A.values() if a["res"])  # csak a nagyatádi teljes táv finisherei
    # ---------------- főoldal ----------------
    top = sorted(A.values(), key=lambda a: (-len(a["res"]), a["name"]))[:10]
    home_hero = hero(
        img="hero-cel.jpg", pos="center 30%", eyebrow="eXtremeMan Nagyatád · teljes táv", title="Finisherek",
        lead=(f"3,8 km úszás · 180 km kerékpár · 42,2 km futás. Mindenki, aki {years[0]} óta célba ért Nagyatádon – "
              "kattints egy névre az eredményekért és a trendgrafikonokért."),
        stats=[(huint(n_fin), "finisher"), (huint(n_res), "célba érés"), (len(years), "verseny"),
               (huint(len(Y[years[-1]])), f"célba érkező, {years[-1]}"),
               (fmt(best["t"]), f'pályacsúcs · <a href="{best["a"]["path"]}">{esc(best["a"]["name"])}</a>, {best["year"]}')])
    content = f"""
    <div class="page-head">
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
        canonical=SITE, content=content, years_html=years_html, hero_html=home_hero,
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
      <div class="eyebrow"><a href="evek/">← Évek</a></div>
      <h1><span class="h1-pre">eXtremeMan Nagyatád eredmények</span> {y}</h1>
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
            jsonld=[crumbs(("Finisherek", SITE), ("Évek", SITE + "evek/"), (str(y), url))],
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
        # további versenyek sorozatonként összevonva, pl. „Balatonszemes duatlon 2024–2026 (3×)”
        ser = {}
        for x in oth:
            ser.setdefault(x["race"]["series_name"], []).append(x["race"]["year"])
        ser_items = [f"{nm} {min(ys)}" + (f"–{max(ys)}" if max(ys) != min(ys) else "") + (f" ({len(ys)}×)" if len(ys) > 1 else "")
                     for nm, ys in sorted(ser.items(), key=lambda kv: (-len(kv[1]), -max(kv[1])))]

        def ser_text(room: int) -> str:
            """A sorozatok listája, amennyi a megadott helyre befér (legalább az első)."""
            t = ser_items[0] if ser_items else ""
            for it in ser_items[1:]:
                if len(t) + 2 + len(it) <= room:
                    t += ", " + it
            return t
        per = {}
        for x in oth:
            k = x["race"]["series"]
            per.setdefault(k, [x["race"]["series_name"], 0])[1] += 1
        chips = "".join(f'<button type="button" class="chip" data-scroll="s-{k}">{esc(nm)} <b>{n}×</b></button>'
                        for k, (nm, n) in sorted(per.items(), key=lambda kv: (-kv[1][1], kv[0])))
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
      <div class="eyebrow"><a href="./">← Finisherek</a></div>
      <h1>{esc(a['name'])}</h1>
      <p class="lead">{lead}. Legjobb ideje {fmt(b['t'])} ({b['year']}, {b['pos']}. hely).</p>
      <div class="chips" id="otherSummary">{f'<span class="chips-label">Versenyei:</span><span class="chip chip-main">Nagyatád teljes táv <b>{len(res)}×</b></span>{chips}' if oth else ''}</div>
    </div>
    <section class="card"><h2>Nagyatád – teljes táv</h2><div class="table-wrap"><table>
      <thead><tr><th>Év</th><th class="r">Célidő</th><th class="r">Helyezés</th>{head}</tr></thead>
      <tbody>{rows}</tbody></table></div></section>{other_table(oth) if oth else ''}"""
            title = f"{a['name']} – eXtremeMan Nagyatád eredmények"
            d0 = (f"{a['name']} {len(res)}× teljesítette az eXtremeMan Nagyatád teljes távját ({span}). "
                  f"Legjobb idő: {fmt(b['t'])} ({b['year']})." if len(res) > 1 else
                  f"{a['name']} teljesítette az eXtremeMan Nagyatád teljes távját ({b['year']}): "
                  f"{fmt(b['t'])}, {b['pos']}. hely.")
            more = f"További versenyek: {ser_text(158 - len(d0) - 22)}." if oth else ""
            desc = fit(d0, more)
            if len(res) > 1:  # a legutóbbi eredmények, amennyi még befér
                t = ""
                for r in reversed(res[-3:]):
                    nxt = (t + ", " if t else "") + f"{r['year']}: {fmt(r['t'])}"
                    if len(desc) + len(" Eredmények: ") + len(nxt) + 1 > 158:
                        break
                    t = nxt
                if t:
                    desc += f" Eredmények: {t}."
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
      <div class="eyebrow"><a href="versenyek/">← Versenyek</a></div>
      <h1>{esc(a['name'])}</h1>
      <p class="lead">{lead}.</p>
    </div>{other_table(oth)}"""
            title = f"{a['name']} – eXtremeMan eredmények"
            head = f"{a['name']} eXtremeMan eredményei ({span}):"
            desc = fit(f"{head} {ser_text(146 - len(head))}.", "Idők, helyezések, részidők.")
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
      <div class="eyebrow"><a href="versenyek/">← Versenyek</a></div>
      <h1>{esc(rc['series_name'])} {rc['year']} <span class="h1-sub">{esc(rc['name'])}</span></h1>
      <p class="lead">{rc['n']} célba érkező{f" · győztes: {esc(w['a']['name'])} ({fmt(w['t'])})" if w else ''}.</p>
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
    <div class="page-head">
      <p class="lead">{len(RACES)} verseny, {sum(rc['n'] for rc in RACES)} célba érkezés 2015 óta.</p></div>{blocks}""",
        hero_html=hero(img="hero-bringa.jpg", pos="center 55%", compact=True, eyebrow="eXtremeMan · 2015 – 2026", title="Versenyek",
                       lead="Az összes eXtremeMan verseny az EvoChip eredményeiből: Nagyatád többi táva, Kaposvár, Gyékényes, "
                            "Balatonszemes, Tab, Velence, Székesfehérvár, Nágocs."),
        years_html=years_html, jsonld=[crumbs(("Finisherek", SITE), ("Versenyek", SITE + "versenyek/"))],
    ), encoding="utf-8")
    urls.append((SITE + "versenyek/", "0.7"))

    # ---------------- Évek, Rekordok (statikus változat) ----------------
    yrows = "".join(
        f'<tr><td><a href="ev/{y}/">{y}</a></td><td class="r">{len(Y[y])}</td>'
        f'<td><a href="{Y[y][0]["a"]["path"]}">{esc(Y[y][0]["a"]["name"])}</a></td><td class="r">{fmt(Y[y][0]["t"])}</td>'
        f'<td class="r">{fmt(median([r["t"] for r in Y[y]]))}</td></tr>' for y in reversed(years))
    out = ROOT / "evek" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page(
        depth=1, title="Évek – eXtremeMan Nagyatád finisherek",
        description=f"Az eXtremeMan Nagyatád teljes táv évenként {years[0]}–{years[-1]}: célba érkezők száma, győztesek, győztes és medián idők.",
        canonical=SITE + "evek/", years_html=years_html,
        content=f"""
    <div class="page-head"><p class="lead">{len(years)} verseny, {n_res} célba érés.</p></div>
    <section class="card"><div class="table-wrap"><table>
      <thead><tr><th>Év</th><th class="r">Célba érkezők</th><th>Győztes</th><th class="r">Győztes idő</th><th class="r">Medián</th></tr></thead>
      <tbody>{yrows}</tbody></table></div></section>""",
        jsonld=[crumbs(("Finisherek", SITE), ("Évek", SITE + "evek/"))],
        hero_html=hero(img="hero-uszas.jpg", pos="center 65%", compact=True, eyebrow=f"eXtremeMan Nagyatád · {years[0]} – {years[-1]}",
                       title="Évek", lead=f"{len(years)} verseny, összesen {huint(n_res)} célba érés. Kattints egy évre a teljes eredménylistáért."),
    ), encoding="utf-8")
    urls.append((SITE + "evek/", "0.7"))

    fin = [a for a in A.values() if a["res"]]
    fastest = sorted(fin, key=lambda a: min(r["t"] for r in a["res"]))[:25]
    most = sorted(fin, key=lambda a: (-len(a["res"]), a["name"]))[:25]
    li = lambda arr, val: "".join(f'<li><span class="pos">{i + 1}.</span><a class="who" href="{a["path"]}">{esc(a["name"])}</a>'
                                 f'<span class="val">{val(a)}</span></li>' for i, a in enumerate(arr))
    out = ROOT / "rekordok" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page(
        depth=1, title="Rekordok – eXtremeMan Nagyatád finisherek",
        description="eXtremeMan Nagyatád toplisták: leggyorsabb egyéni idők, legtöbb célba érés, leghosszabb sorozat.",
        canonical=SITE + "rekordok/", years_html=years_html,
        content=f"""
    <div class="grid-2">
      <section class="card"><h2>Leggyorsabb egyéni idők</h2><ol class="rank-list">{li(fastest, lambda a: fmt(min(r["t"] for r in a["res"])))}</ol></section>
      <section class="card"><h2>Legtöbb célba érés</h2><ol class="rank-list">{li(most, lambda a: f"{len(a['res'])}×")}</ol></section>
    </div>""",
        jsonld=[crumbs(("Finisherek", SITE), ("Rekordok", SITE + "rekordok/"))],
        hero_html=hero(img="hero-erem.jpg", pos="center 25%", compact=True, eyebrow="eXtremeMan Nagyatád · toplisták", title="Rekordok",
                       lead="A leggyorsabbak, a legkitartóbbak és a leghűségesebbek a teljes távú egyéni célba érkezők között."),
    ), encoding="utf-8")
    urls.append((SITE + "rekordok/", "0.7"))
    urls.append((SITE + "adatvedelem.html", "0.3"))  # scripts/build_adatvedelem.py generálja

    # ---------------- átirányítások: megszűnt (összevont) versenyzői azonosítók ----------------
    # data/redirects.json: {"régi id": [új id, régi név]} – a régi link az új adatlapra visz
    rd_path = ROOT / "data" / "redirects.json"
    rd = json.loads(rd_path.read_text(encoding="utf-8")) if rd_path.exists() else {}
    n_rd = 0
    for old_id, (new_id, old_name) in rd.items():
        while str(new_id) in rd and str(new_id) != old_id and int(new_id) not in A:  # láncolt átirányítás
            new_id = rd[str(new_id)][0]
        tgt = A.get(int(new_id))
        if not tgt or int(old_id) in A:
            continue
        url = SITE + tgt["path"]
        stub = (f'<!doctype html><html lang="hu"><head><meta charset="utf-8"><title>{html.escape(tgt["name"])}</title>'
                f'<meta name="robots" content="noindex"><link rel="canonical" href="{url}">'
                f'<meta http-equiv="refresh" content="0; url={url}"></head>'
                f'<body><p>Az adatlap új címe: <a href="{url}">{html.escape(tgt["name"])}</a></p></body></html>\n')
        d_ = ROOT / f"versenyzo/{old_id}-{slug(old_name)}"
        d_.mkdir(parents=True, exist_ok=True)
        (d_ / "index.html").write_text(stub, encoding="utf-8")
        n_rd += 1

    # ---------------- 404.html: ismeretlen cím esetén is az app töltődik be ----------------
    from urllib.parse import urlparse
    nf = page(depth=0, title="eXtremeMan Nagyatád finisherek", description="Az oldal nem található.",
              canonical=SITE, content='<div class="loading" role="status"><span class="spinner"></span> Betöltés…</div>',
              years_html=years_html, jsonld=[])
    nf = nf.replace('<base href="./">', f'<base href="{urlparse(SITE).path}">')
    nf = nf.replace("<title>", '<meta name="robots" content="noindex">\n  <title>', 1)
    (ROOT / "404.html").write_text(nf, encoding="utf-8")

    today = date.today().isoformat()
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f"  <url><loc>{esc(u)}</loc><lastmod>{today}</lastmod><priority>{p}</priority></url>" for u, p in urls]
    sm.append("</urlset>")
    (ROOT / "sitemap.xml").write_text("\n".join(sm) + "\n", encoding="utf-8")
    print(f"Kész: index.html, {len(years)} év-oldal, {n_core} nagyatádi + {n_side} további versenyző-oldal, "
          f"{len(RACES)} versenyoldal, {n_rd} átirányítás, sitemap.xml ({len(urls)} URL)")


if __name__ == "__main__":
    main()
