# eXtremeMan Nagyatád – Finisherek

Az eXtremeMan Nagyatád teljes távú (3,8 km úszás · 180 km kerékpár · 42,2 km futás)
**egyéni** célba érkezőinek névsora 1990-től, az
[extremetour.hu Finisherek ABC](https://www.extremetour.hu/finisherekabc) mintájára,
kiegészítve a 2026-os eredményekkel és 2022-től a részidőkkel (EvoChip).

Statikus weboldal (HTML + CSS + JS, build lépés nélkül), GitHub Pages-en publikálva:
https://lederermate.github.io/ExtremeManFinishers/

## Mit tud az oldal

- **Finisherek** – kereshető, ABC szerint szűrhető, rendezhető névsor (név, célba érések
  száma, legjobb idő, legutóbbi év), minden névnél mini trendvonal.
- **Versenyző adatlap** – trendgrafikon évenkénti célidőkkel, a mezőny mediánjához
  viszonyítva; váltható „helyezés a mezőnyben” nézet (kiszűri az időjárás hatását);
  részidők (ahol vannak) szakaszonkénti helyezéssel; teljes eredménytáblázat.
  Egyszeres célba érőknél: hol helyezkedett el az adott év mezőnyében.
- **Évek** – célba érkezők száma, győztes és medián idő évenként.
- **Év oldal** – célidő-eloszlás, leggyorsabb részidők, teljes eredménylista.
- **Rekordok** – leggyorsabb idők, legtöbb célba érés, leghosszabb sorozat és pályafutás.
- Világos / sötét téma, mobilbarát.

## Fájlok

| Fájl | Mire való |
| --- | --- |
| `index.html`, `style.css`, `app.js` | az oldal |
| `config.js` | Supabase elérés (üresen: a beépített pillanatképből fut) |
| `data/finishers.json` | az összes adat tömör formában – tartalék, ha a Supabase nem elérhető |
| `supabase/schema.sql` | adatbázis séma + jogosultságok + `finisher_data()` függvény |
| `supabase/seed.sql` | az adatok betöltése (generált fájl) |
| `supabase/seed_laps.sql` | köztes mérőpontok (köridők) betöltése (generált fájl) |
| `data/laps/`, `data/splits/` | köztes mérőpontok rajtszám, ill. versenyző szerint (tartalék) |
| `scripts/` | adatgyűjtő és -építő szkriptek (lásd lent) |
| `data/extremetour.json` | az extremetour.hu-ról letöltött nyers adatok (1990–2025) |
| `data/evochip_<év>.json`, `sources/evochip/` | az EvoChip exportok (2022–2026) és a kinyert adatok |
| `data/overrides.json` | kézi névpárosítások |
| `data/match_report.txt` | a párosítás naplója (EvoChip ↔ extremetour) |

## Beüzemelés

### 1. Supabase adatbázis

1. https://supabase.com → **New project** (régió: *Central EU (Frankfurt)*, az ingyenes csomag elég).
2. **SQL Editor → New query**: másold be a `supabase/schema.sql` tartalmát → **Run**.
3. **SQL Editor → New query**: másold be a `supabase/seed.sql` tartalmát → **Run**
   (kb. 470 KB, pár másodperc), majd ugyanígy a `supabase/seed_laps.sql`-t (köridők). Ellenőrzés: *Table Editor* → `athletes` ≈ 3800 sor,
   `results` ≈ 10 780 sor.
4. **Project Settings → API Keys**: másold ki a projekt URL-t és a **publishable**
   (vagy régi *anon*) kulcsot, és írd be a `config.js`-be.

> A publishable/anon kulcs nyilvános, böngészőbe szánt kulcs. A **secret /
> service_role** kulcsot soha ne tedd a weboldalba!

Az adatbázis a böngészőből csak olvasható (RLS). Az oldal egyetlen hívással
(`rpc/finisher_data`) tölti le az összes adatot; ha ez nem sikerül, automatikusan a
`data/finishers.json` pillanatképet használja.

> Az ingyenes Supabase projekt 7 nap inaktivitás után szünetel. Ilyenkor az oldal
> továbbra is működik a pillanatképből; a projektet a Supabase felületén egy
> kattintással lehet újraindítani.

### 2. GitHub Pages

**Settings → Pages → Build and deployment**: *Source:* **Deploy from a branch**,
*Branch:* **main**, mappa: **/ (root)** → **Save**. Pár perc múlva él az oldal.

## Adatok frissítése

```bash
pip install openpyxl

# 1990–2025 újratöltése az extremetour.hu-ról (36 oldal letöltése)
python3 scripts/scrape_extremetour.py

# EvoChip XLSX exportok (2022-től vannak részidők; 2020: eXtremeManNagyatad20VIn):
#   https://www.evochip.hu/results/xlsgen.php?eventid=Nagyatad26VIn&lang=hu&distance=xman
for y in 22 23 24 25 26; do
  python3 scripts/import_evochip.py sources/evochip/Nagyatad${y}VIn_xman.xlsx 20$y
done

# összefésülés -> supabase/seed.sql, data/finishers.json, data/match_report.txt
python3 scripts/build_data.py
```

Köztes mérőpontok (úszás körök, kerékpár szakaszok, futás körök) az EvoChip egyéni
adatlapjairól (évente kb. 300 oldal; a letöltött oldalak a `.cache/` mappába kerülnek):

```bash
for y in 22 23 24 25 26; do
  python3 scripts/scrape_evochip_laps.py Nagyatad${y}VIn 20$y
done
python3 scripts/build_data.py   # -> data/splits/<év>.json, supabase/seed_laps.sql
python3 scripts/build_pages.py  # -> index.html, versenyzo/*, ev/*, sitemap.xml (SEO)
```

További eXtremeMan versenyek (Kaposvár, Gyékényes, Balatonszemes, Tab, Velence,
Székesfehérvár, Nágocs, Nagyatád többi táva) 2015-től – az események listája a
szkript elején (`EVENTS`):

```bash
python3 scripts/evochip_races.py     # -> data/races/*.json
python3 scripts/scrape_other_laps.py # köztes mérőpontok -> data/laps_other/*.json
python3 scripts/build_data.py        # -> supabase/seed_races.sql, seed_race_laps*.sql
```

A versenyző adatlapján a „További eXtremeMan versenyek” táblázatban a köridős
versenyeknél a **Körönként ▾** gomb nyitja le a részletes grafikonokat.
A `data/anomalies.txt` a gyanús adatokat listázza (pl. két eredmény egy napon,
helyezés-ugrás, női/férfi ütközés) – új adatok betöltése után érdemes átnézni.

**Automatikus frissítés:** ha a `supabase/` mappa változása felkerül a `main` ágra, a
`.github/workflows/supabase-seed.yml` munkafolyamat magától lefuttatja az SQL fájlokat
(a `SUPABASE_DB_URL` secretben megadott Session pooler címmel). Kézzel: Actions →
„Supabase adatbázis frissítése” → Run workflow.

Kézi futtatás esetén az SQL Editorban sorban: `schema.sql` (ha változott), `seed.sql`,
`seed_laps*.sql`, `seed_races.sql`, `seed_race_laps*.sql`
(a teljes tartalmat cserélik), és a változásokat feltölteni a GitHubra.
Ha a `schema.sql` változott, előbb azt (többször is futtatható).

### Párosítás

- **Az extremetour.hu-n is szereplő években (2022–2025)** az EvoChip sorok célidő
  (±3 mp) és névhasonlóság alapján kapcsolódnak a meglévő eredményekhez – így kapnak
  részidőt, a versenyzők pedig születési évet és „EvoChip-névjegyet” (az EvoChip
  névírása + szül. év, licencszám). Pl. az EvoChip „Szilágyi Tamás (1991)”
  = extremetour „Szilágyi Tamás László”.
- **Új évben (2026)** a sorrend: kézi párosítás → EvoChip név + szül. év / licencszám
  egy korábbi évből → egyértelmű extremetour névegyezés → névrészlet + szül. év.
  Ha egyik sem egyértelmű, új versenyzőként kerül be, és a `data/match_report.txt`-ben
  **KÉTES** jelölést kap.
- Célidővel, de helyezés nélkül szereplő versenyzők (pl. időbüntetés) beszámítanak –
  az extremetour.hu is így számol (2023: Bars Tamás).

Kézi javítás a `data/overrides.json`-ban:

```json
{ "2026": { "Varga István": 885, "Nagy Gábor": "new" } }
```

(a szám az extremetour.hu versenyző-azonosítója, pl. `extremetour.hu/finisher/885`).

## Keresőoptimalizálás (SEO)

- Címek: rendes URL-ek névvel (pl. `versenyzo/1794-kolonics-tamas/`, `ev/2019/`,
  `verseny/2026-gyekenyes-t51/`); az app History API-val navigál, a régi `#/...`
  linkeket átírja. Ismeretlen címre a `404.html` tölti be az appot.
- Az oldal sablonja a `templates/page.html`; a `scripts/build_pages.py` ebből generálja
  a főoldalt (`index.html`), minden versenyzőnek egy saját oldalt
  (`versenyzo/<id>-<név>/`) és minden évnek egyet (`ev/<év>/`). A tartalom (név,
  eredmények, részidők) benne van a HTML-ben, így a keresők látják; betöltés után az
  `app.js` ugyanott az interaktív nézetet mutatja. **Az `index.html`-t ne szerkeszd
  kézzel – a sablont módosítsd, és futtasd újra a szkriptet.**
- Oldalanként egyedi cím, leírás, kanonikus URL, Open Graph / Twitter kártya
  (`images/og.jpg`) és JSON-LD (WebSite, Dataset, ProfilePage, BreadcrumbList).
- **Betöltéskori ugrás (CLS) ellen:** a fejlécfotót (hero) a `build_pages.py` a statikus HTML-be is
  beleírja, pontosan az `app.js` `setHero()` jelölésével – ha az egyiket módosítod, a másikat is
  (a JS a meglévő fotót nem rajzolja újra, csak a szöveget). A versenyzői chipeket az app az első
  betöltéskor a statikus oldalról veszi át; a `main` legalább képernyőnyi magas, így a lábléc nem ugrik.
- H1-ek: a hero H1-e a felirattal együtt kulcsszavas („eXtremeMan Nagyatád · teljes táv Finisherek”),
  az év- és versenyoldalaké is („eXtremeMan Nagyatád eredmények 2026”, „Kaposvár 2015 eXtremeMan 113 Kaposvár”).
- Meta description legfeljebb ~158 karakter (`fit()`), a további versenyek sorozatonként összevonva.
- `sitemap.xml` minden oldallal; a `robots.txt` a `lederermate.github.io` repóban van
  (a domain gyökerében kell lennie).
- Google Search Console: a `https://lederermate.github.io/ExtremeManFinishers/` címet
  URL-előtagként felvenni, és beküldeni a `sitemap.xml`-t.

## Források

A teljes, linkelt forráslista és az adatvédelmi tájékoztató: `adatvedelem.html`
(generálja: `python3 scripts/build_adatvedelem.py` – új év vagy esemény hozzáadása után futtasd újra;
az adatkérésekhez szóló e-mail címet a szkript elején, a `CONTACT_EMAIL`-ben lehet megadni).


- Finisherek 1990–2025: [extremetour.hu](https://www.extremetour.hu/finisherekabc)
- Részidők 2022–2026, eredmények 2026: [EvoChip](https://www.evochip.hu/results/)
- Betűtípusok: Oswald, Source Sans 3 (SIL Open Font License, `fonts/`)
- Fotók: [extrememan.hu](https://www.extrememan.hu/) (forrásmegjelöléssel)
