// eXtremeMan finisherek – adatbázis beállítások.
//
// Az oldal elsőként a statikus, tömör adatfájlokat tölti be (data/finishers.min.json, data/other/ –
// gyorsabbak és a CDN gyorsítótárazza őket); a Supabase csak tartalék, ha ezek nem érhetők el.
// Üresen hagyva tartalékként a data/finishers.json pillanatkép töltődik be.
//
// Élesítéshez (Supabase): Project Settings → API Keys
//   supabaseUrl: a projekt URL-je, pl. https://abcd1234.supabase.co
//   supabaseKey: a "publishable" (sb_publishable_...) vagy a régi "anon" kulcs.
// Ezek a kulcsok nyilvánosak, a böngészőbe szánták őket – a védelmet az
// adatbázis jogosultságai adják (lásd supabase/schema.sql).
// A "secret" / "service_role" kulcsot SOHA ne írd ide!
window.FINISHERS_CONFIG = {
  supabaseUrl: 'https://rvpmblonczssifuwtgnc.supabase.co',
  supabaseKey: 'sb_publishable_b6vqL1BjwUWDTZyB3xlHqw_rF-55Vmq',
};
