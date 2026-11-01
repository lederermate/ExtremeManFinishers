// eXtremeMan finisherek – adatbázis beállítások.
//
// Üresen hagyva az oldal a beépített pillanatképből (data/finishers.json) dolgozik.
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
