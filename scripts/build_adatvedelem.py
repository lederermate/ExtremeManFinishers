#!/usr/bin/env python3
"""Az adatvédelmi és forrásoldal (adatvedelem.html) generálása.

A forráslista automatikusan frissül:
  - extremetour.hu évek:            data/extremetour.json
  - EvoChip, Nagyatád teljes táv:   sources/evochip/*.xlsx (fájlnév = EvoChip eseményazonosító)
  - EvoChip, további versenyek:     scripts/evochip_races.py EVENTS listája
  - az EvoChip események nevei:     data/evochip_events.json (a hiányzókat letölti)

Önálló oldal (nincs benne az app.js), ezért az app útválasztója nem írja felül;
a .html végződés miatt a belső linkkezelő is rendes oldalbetöltéssel nyitja meg.

Használat: python3 scripts/build_adatvedelem.py   (új forrás / év hozzáadása után)
"""
import ast
import html
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://lederermate.github.io/ExtremeManFinishers/"
URL = SITE + "adatvedelem.html"
REPO = "https://github.com/lederermate/ExtremeManFinishers"
# Ha van e-mail cím az adatkérésekhez, ide írd (pl. "valaki@example.com");
# üresen a GitHub-on keresztüli kapcsolatfelvétel jelenik meg.
CONTACT_EMAIL = "lederer.mate@gmail.com"

ET = "https://www.extremetour.hu"
EVO = "https://www.evochip.hu/results/result.php"


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def ext(url: str, text: str) -> str:
    return f'<a href="{esc(url)}" target="_blank" rel="noopener">{text}</a>'


def evo_url(event: str) -> str:
    return f"{EVO}?eventid={event}&lang=hu"


TITLES = ROOT / "data" / "evochip_events.json"


def event_titles(events) -> dict:
    """Az EvoChip események hivatalos nevei (data/evochip_events.json); a hiányzókat letölti."""
    import urllib.request
    titles = json.loads(TITLES.read_text(encoding="utf-8")) if TITLES.exists() else {}
    for ev in events:
        if ev in titles:
            continue
        try:
            req = urllib.request.Request(evo_url(ev), headers={"User-Agent": "ExtremeManFinishers importer"})
            page = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
            m = re.search(r"<h1>([^<]+)", page)
            if m and m.group(1).strip():
                titles[ev] = re.sub(r"\s+", " ", html.unescape(m.group(1))).strip()
        except OSError as e:
            print(f"  {ev}: a név nem tölthető le ({e})")
    TITLES.write_text(json.dumps(dict(sorted(titles.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return titles


def load_sources():
    et_years = sorted({r["year"] for r in json.loads((ROOT / "data/extremetour.json").read_text(encoding="utf-8"))["results"]})

    nagyatad = []
    for f in sorted((ROOT / "sources/evochip").glob("*.xlsx")):
        event = re.sub(r"_xman$", "", f.stem)
        m = re.search(r"(\d\d)[A-Z][A-Za-z]{2}$", event)
        if m:
            nagyatad.append((2000 + int(m.group(1)), event))
    nagyatad.sort()

    tree = ast.parse((ROOT / "scripts/evochip_races.py").read_text(encoding="utf-8"))
    consts = {t.targets[0].id: ast.literal_eval(t.value) for t in tree.body
              if isinstance(t, ast.Assign) and isinstance(t.targets[0], ast.Name) and t.targets[0].id in ("EVENTS", "SERIES")}
    others = sorted(consts["EVENTS"], key=lambda e: (e[0], consts["SERIES"][e[2]], e[1]))
    return et_years, nagyatad, others, consts["SERIES"]


def main() -> None:
    et_years, nagyatad, others, series = load_sources()
    n_sources = 3 + len(et_years) + len(nagyatad) + len(others)
    titles = event_titles([ev for _, ev in nagyatad] + [ev for _, ev, _ in others])

    if CONTACT_EMAIL:
        contact = f'e-mailben, a <a href="mailto:{esc(CONTACT_EMAIL)}">{esc(CONTACT_EMAIL)}</a> címre'
    else:
        contact = (f'a {ext("https://github.com/lederermate", "GitHub-profilon")} keresztül, vagy a projekt '
                   f'{ext(REPO + "/issues", "hibajegy-oldalán")} (ez utóbbi nyilvános, ezért ott ne adj meg több személyes adatot, mint amennyi a kéréshez kell)')

    by_year = {}
    for y, ev, s in others:
        name = titles.get(ev) or series[s]
        city = series[s].split()[0].rstrip(" –")
        if city.lower() not in name.lower():  # pl. „eXtremeMan 113” -> „eXtremeMan 113 (Kaposvár)”
            name += f" ({series[s]})"
        by_year.setdefault(y, []).append((name, ev))
    other_html = "".join(
        f'<div class="src-year"><h4>{y}</h4><ul>'
        + "".join(f'<li>{ext(evo_url(ev), esc(name))}</li>' for name, ev in evs)
        + "</ul></div>"
        for y, evs in sorted(by_year.items()))

    content = f"""
    <div class="page-head">
      <div class="eyebrow"><a href="./">← Finisherek</a></div>
      <h1>Adatvédelem és források</h1>
      <p class="lead">Ez az oldal <b>kizárólag nyilvánosan elérhető</b>, a versenyek szervezői és időmérői által
        már közzétett eredményekből dolgozik. Minden adat forrását alább, linkkel együtt felsoroljuk.
        A látogatókról nem gyűjtünk adatot.</p>
    </div>

    <section class="card prose">
      <h2>Röviden</h2>
      <ul>
        <li>Az eredmények <b>nyilvános eredménylistákból</b> származnak (extremetour.hu, EvoChip) – új, nem nyilvános adatot nem gyűjtünk, és senkitől nem kérünk be adatot.</li>
        <li>Az oldal célja a verseny történetének és a célba érkezők teljesítményének bemutatása (sporttörténeti statisztika). Nem kereskedelmi célú, nincs rajta hirdetés.</li>
        <li>Nincs regisztráció, nincsenek sütik, nincs látogatottságmérés vagy követés.</li>
        <li>Ha szerepelsz az oldalon, és szeretnéd, hogy az adataidat javítsuk vagy eltávolítsuk, <a href="adatvedelem.html#kerelem">írj nekünk</a>.</li>
      </ul>
    </section>

    <section class="card prose">
      <h2>Milyen adatok szerepelnek az oldalon?</h2>
      <p>Csak az, ami a forrásként megjelölt nyilvános eredménylistákban is szerepel:</p>
      <ul>
        <li>név (a forrásban közölt írásmóddal),</li>
        <li>születési év, nem és egyesület – ahol a forrás közli (az EvoChip-listákban 2015-től),</li>
        <li>célidő, helyezés, részidők és köztes mérőpontok (úszás, depók, kerékpár, futás),</li>
        <li>a fentiekből számolt statisztikák (pl. legjobb idő, célba érések száma, helyezés a mezőnyben, trendgrafikon).</li>
      </ul>
      <p>Nem szerepel: elérhetőség (cím, telefon, e-mail), licencszám, pontos születési dátum vagy bármilyen más,
        az eredménylistákon túli adat. A versenyzők párosítása (ugyanaz a személy különböző években) a név, a születési év
        és a célidő alapján, a nyilvános adatokból történik.</p>
    </section>

    <section class="card prose">
      <h2>Mire használjuk, és milyen alapon?</h2>
      <p>A nyilvánosan közzétett versenyeredményeket egy helyen, kereshető formában tesszük elérhetővé, hogy a
        versenyzők, szurkolók és a sportág iránt érdeklődők visszanézhessék az eredményeket és a fejlődést.
        Az adatok kezelésének jogalapja az általános adatvédelmi rendelet (GDPR) 6. cikk (1) bekezdés f) pontja szerinti
        jogos érdek: a már nyilvános sporteredmények sporttörténeti célú, összesített bemutatása.
        Az adatokat nem adjuk át senkinek, nem használjuk marketingre vagy profilalkotásra.</p>
    </section>

    <section class="card prose" id="kerelem">
      <h2>Javítás, eltávolítás, tiltakozás</h2>
      <p>Ha szerepelsz az oldalon, kérheted az adataid javítását, a születési éved / egyesületed elrejtését vagy a
        teljes eltávolításukat, illetve tiltakozhatsz az adatkezelés ellen. A kérést {contact} küldheted el.
        Írd meg, melyik adatlapról van szó (a link elég); a kérést indokolatlan késedelem nélkül, legkésőbb egy hónapon belül teljesítjük.</p>
      <p>Az eltávolítás ezt az oldalt érinti – az eredeti eredménylistákon (lásd a forrásokat) az adatok a szervezőknél
        maradnak, azok módosítását náluk lehet kérni. Panasszal a Nemzeti Adatvédelmi és Információszabadság Hatósághoz
        ({ext("https://www.naih.hu/", "naih.hu")}) is fordulhatsz.</p>
    </section>

    <section class="card prose">
      <h2>A látogatókról</h2>
      <ul>
        <li><b>Nincsenek sütik és nincs követés</b> (nincs Google Analytics, közösségi gomb, hirdetés).</li>
        <li>A világos/sötét téma választása csak a <b>saját böngésződben</b> tárolódik (localStorage), hozzánk nem jut el.</li>
        <li>A betűtípusok és a képek erről az oldalról töltődnek be, nem külső szolgáltatótól.</li>
        <li>Tárhely: az oldalt a {ext("https://pages.github.com/", "GitHub Pages")} szolgálja ki; a GitHub technikai
          naplót vezethet a kérésekről (pl. IP-cím) – lásd a {ext("https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement", "GitHub adatvédelmi nyilatkozatát")}.</li>
        <li>Adatbázis: az eredményeket a böngésződ a {ext("https://supabase.com/privacy", "Supabase")} szolgáltatásból tölti le
          (ha nem érhető el, az oldalba épített pillanatképből). Ilyenkor a Supabase is technikai naplót vezethet.</li>
        <li>A külső oldalakra (források, fotók) mutató linkek csak akkor nyílnak meg, ha rájuk kattintasz.</li>
      </ul>
    </section>

    <section class="card prose" id="forrasok">
      <h2>Források – teljes lista ({n_sources} link)</h2>
      <p>Az adatok a lenti nyilvános oldalakról származnak. Ahol a források eltérnek, az időmérő (EvoChip) adatait
        tekintjük pontosabbnak; a párosítások és javítások a projekt nyilvános
        {ext(REPO, "forráskódjában")} is ellenőrizhetők.</p>

      <h3>1. extremetour.hu – Nagyatád teljes táv, célba érkezők {et_years[0]}–{et_years[-1]}</h3>
      <p>Az eXtremeMan / Extremetour szervezők nyilvános finisher-nyilvántartása (név, helyezés, célidő).</p>
      <ul>
        <li>{ext(ET + "/finisherekabc", "Finisherek ABC sorrendben")} – {esc(ET)}/finisherekabc</li>
        <li>{ext(ET + "/finisherekevlista", "Finisherek évenként – évlista")} – {esc(ET)}/finisherekevlista</li>
      </ul>
      <p class="src-label">Évenkénti eredménylisták:</p>
      <p class="src-years">{" ".join(ext(f"{ET}/finisherekevben/{y}", str(y)) for y in et_years)}</p>

      <h3>2. EvoChip – Nagyatád teljes táv, eredmények és részidők {nagyatad[0][0]}–{nagyatad[-1][0]}</h3>
      <p>Az {ext("https://www.evochip.hu/", "EvoChip Timing Team")} hivatalos időmérő nyilvános eredménylistái
        (célidő, helyezés, születési év, nem, egyesület, részidők és köztes mérőpontok; {nagyatad[-1][0]}-ban a teljes eredménylista is innen származik).</p>
      <ul class="src-cols">
        {"".join(f'<li>{y}: {ext(evo_url(ev), esc(titles.get(ev, "eredménylista")))}</li>' for y, ev in nagyatad)}
      </ul>

      <h3>3. EvoChip – további eXtremeMan versenyek ({len(others)} esemény)</h3>
      <p>A „Versenyek” menüpont és a versenyzői adatlapok „További eXtremeMan versenyek” táblázata
        (felnőtt egyéni versenyek; a váltók és a gyermek-, serdülő-, ifjúsági és junior kategóriák nem szerepelnek).</p>
      <div class="src-grid">{other_html}</div>

      <h3>4. Fotók</h3>
      <p>A fejlécfotók a szervező {ext("https://www.extrememan.hu/", "extrememan.hu")} oldalán közzétett versenyfotók,
        forrásmegjelöléssel. Ha valamelyik fotón szerepelsz, és szeretnéd, hogy lecseréljük, <a href="adatvedelem.html#kerelem">szólj</a>.</p>
    </section>

    <p class="muted updated">Utolsó frissítés: {date.today().isoformat()}</p>"""

    style = """<style>
    .prose p, .prose ul { max-width: 75ch; }
    .prose ul { padding-left: 1.2em; margin: 10px 0; }
    .prose li { margin: 4px 0; }
    .prose h2 { margin-bottom: 10px; }
    .prose a { color: var(--accent-ink); text-decoration: underline; text-underline-offset: 2px; text-decoration-thickness: 1px; }
    .prose h3 { font-size: 16px; margin: 22px 0 6px; }
    .src-label { margin-bottom: 4px; font-weight: 600; }
    .src-years { display: flex; flex-wrap: wrap; gap: 6px 12px; font-variant-numeric: tabular-nums; }
    .src-cols { columns: 2 260px; }
    .src-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 4px 20px; }
    .src-grid h4 { margin: 12px 0 2px; font-size: 14px; }
    .src-grid ul { list-style: none; padding: 0; margin: 0; }
    .src-grid li { margin: 3px 0; }
    .updated { margin-top: 20px; font-size: 13px; }
  </style>"""

    title = "Adatvédelem és források – eXtremeMan Nagyatád finisherek"
    desc = ("Az oldal kizárólag nyilvánosan elérhető versenyeredményekből dolgozik (extremetour.hu, EvoChip). "
            "Milyen adatok szerepelnek, honnan, és hogyan kérheted a javításukat vagy eltávolításukat.")
    seo = f"""<title>{esc(title)}</title>
  <meta name="description" content="{esc(desc)}">
  <link rel="canonical" href="{URL}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="eXtremeMan Nagyatád finisherek">
  <meta property="og:locale" content="hu_HU">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(desc)}">
  <meta property="og:url" content="{URL}">
  <meta property="og:image" content="{SITE}images/og.jpg">
  <script type="application/ld+json">{json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Finisherek", "item": SITE},
        {"@type": "ListItem", "position": 2, "name": "Adatvédelem és források", "item": URL}]}, ensure_ascii=False)}</script>
  {style}"""

    t = (ROOT / "templates" / "page.html").read_text(encoding="utf-8")
    out = re.sub(r"<!--seo:start-->.*?<!--seo:end-->", lambda _: seo, t, flags=re.S)
    out = out.replace("<!--base-->", '<base href="./">')
    out = re.sub(r"<!--content:start-->.*?<!--content:end-->", lambda _: content, out, flags=re.S)
    out = re.sub(r"<!--years:start-->.*?<!--years:end-->", "", out, flags=re.S)
    out = out.replace('<div id="hero"></div>', "")
    out = out.replace('<p class="muted" id="dataSource"></p>', "")
    # app.js nélkül: csak a témaváltó kell
    out = re.sub(r'\s*<script src="config\.js"></script>\s*<script src="app\.js"></script>', """
  <script>
    document.getElementById('themeBtn').addEventListener('click', () => {
      const root = document.documentElement;
      const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
      root.dataset.theme = dark ? 'light' : 'dark';
      try { localStorage.setItem('theme', root.dataset.theme); } catch (e) { /* nem baj */ }
    });
  </script>""", out)
    assert "app.js" not in out, "a sablon szkriptjei megváltoztak – frissítsd a cserét"
    (ROOT / "adatvedelem.html").write_text(out, encoding="utf-8")
    print(f"adatvedelem.html kész ({n_sources} forráslink)")


if __name__ == "__main__":
    main()
