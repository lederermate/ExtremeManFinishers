# eXtremeMan Nagyatád – Finisherek

Az eXtremeMan Nagyatád teljes távú (3,8 km úszás · 180 km kerékpár · 42,2 km futás)
**egyéni** célba érkezőinek névsora 1990-től, az
[extremetour.hu Finisherek ABC](https://www.extremetour.hu/finisherekabc) mintájára,
kiegészítve a 2026-os eredményekkel (EvoChip, részidőkkel).

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
| `scripts/` | adatgyűjtő és -építő szkriptek (lásd lent) |
| `data/extremetour.json` | az extremetour.hu-ról letöltött nyers adatok (1990–2025) |
| `data/evochip_2026.json`, `sources/evochip/` | a 2026-os EvoChip export és a kinyert adatok |
| `data/overrides.json` | kézi névpárosítások |
| `data/match_report.txt` | a 2026-os nevek párosításának naplója |

## Beüzemelés

### 1. Supabase adatbázis

1. https://supabase.com → **New project** (régió: *Central EU (Frankfurt)*, az ingyenes csomag elég).
2. **SQL Editor → New query**: másold be a `supabase/schema.sql` tartalmát → **Run**.
3. **SQL Editor → New query**: másold be a `supabase/seed.sql` tartalmát → **Run**
   (kb. 400 KB, pár másodperc). Ellenőrzés: *Table Editor* → `athletes` ≈ 3800 sor,
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

# új év az EvoChip XLSX exportjából (pl. 2026):
#   https://www.evochip.hu/results/xlsgen.php?eventid=Nagyatad26VIn&lang=hu&distance=xman
python3 scripts/import_evochip.py sources/evochip/Nagyatad26VIn_xman.xlsx 2026

# összefésülés -> supabase/seed.sql, data/finishers.json, data/match_report.txt
python3 scripts/build_data.py
```

Utána a `supabase/seed.sql`-t újra lefuttatni az SQL Editorban (a teljes tartalmat
cseréli), és a változásokat feltölteni a GitHubra.

### Névpárosítás

Az EvoChip nevek az extremetour.hu versenyzőihez név (+ születési év) alapján
kapcsolódnak. Ha egy névhez több korábbi versenyző is tartozik és nem dönthető el,
melyikről van szó, az új versenyzőként kerül be, és a `data/match_report.txt`-ben
**KÉTES** jelölést kap. Kézi javítás a `data/overrides.json`-ban:

```json
{ "2026": { "Varga István": 885, "Nagy Gábor": "new" } }
```

(a szám az extremetour.hu versenyző-azonosítója, pl. `extremetour.hu/finisher/885`).

## Források

- Finisherek 1990–2025: [extremetour.hu](https://www.extremetour.hu/finisherekabc)
- 2026: [EvoChip](https://www.evochip.hu/results/result.php?eventid=Nagyatad26VIn&distance=xman)
- Betűtípusok: Inter, Archivo (SIL Open Font License, `fonts/`)
