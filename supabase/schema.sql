-- =====================================================================
-- eXtremeMan Nagyatád finisherek – adatbázis (Supabase / PostgreSQL)
--
-- Futtatás: Supabase Dashboard → SQL Editor → New query → ezt a fájlt
-- bemásolni → Run. Többször is lefuttatható (idempotens).
-- Utána ugyanígy a supabase/seed.sql-t (az tölti fel az adatokat).
--
-- Biztonsági modell:
--   * Az adatok nyilvánosak (versenyeredmények), a böngésző csak OLVASNI
--     tud (RLS: select policy, írási policy nincs).
--   * Írni csak a Supabase felületéről (Table Editor / SQL Editor) vagy
--     a secret kulccsal lehet – az soha nem kerül a weboldalba.
--
-- Időadatok másodpercben (finish_s = célidő, swim_s / t1_s / bike_s /
-- t2_s / run_s = részidők, ha ismertek).
-- =====================================================================

create table if not exists public.athletes (
  id          integer primary key,               -- 1–99999: extremetour.hu azonosító, 100001-től: új
  name        text     not null check (char_length(name) between 2 and 120),
  birth_year  smallint check (birth_year between 1900 and 2100),
  sex         char(1)  check (sex in ('M', 'F')),
  created_at  timestamptz not null default now()
);

create table if not exists public.results (
  id          bigint generated always as identity primary key,
  athlete_id  integer  not null references public.athletes(id) on delete cascade,
  year        smallint not null check (year between 1990 and 2100),
  pos         smallint check (pos > 0),            -- abszolút helyezés (egyéni, férfi + női együtt)
  finish_s    integer  not null check (finish_s > 0),
  swim_s      integer,
  t1_s        integer,
  bike_s      integer,
  t2_s        integer,
  run_s       integer,
  sex_rank    smallint,                            -- nemenkénti helyezés (ha ismert)
  bib         integer,                             -- rajtszám
  club        text,
  source      text,                                -- extremetour / evochip / kézi
  created_at  timestamptz not null default now(),
  unique (athlete_id, year)
);

create index if not exists results_year_idx on public.results (year);

-- ---------------------------------------------------------------------
-- Jogosultságok: mindenki olvashat, a böngészőből senki sem írhat
-- ---------------------------------------------------------------------
alter table public.athletes enable row level security;
alter table public.results  enable row level security;

drop policy if exists "athletes: public read" on public.athletes;
create policy "athletes: public read" on public.athletes for select to anon, authenticated using (true);

drop policy if exists "results: public read" on public.results;
create policy "results: public read" on public.results for select to anon, authenticated using (true);

revoke insert, update, delete, truncate on public.athletes, public.results from anon, authenticated;
grant select on public.athletes, public.results to anon, authenticated;

-- ---------------------------------------------------------------------
-- Egyetlen hívással visszaadja az összes adatot tömör formában.
-- (A REST API soronként max. 1000 rekordot ad vissza; egy JSON érték
-- esetén ez a korlát nem érvényes, így nem kell lapozni.)
-- ---------------------------------------------------------------------
create or replace function public.finisher_data()
returns json
language sql
stable
security invoker
set search_path = public
as $$
  select json_build_object(
    'athletes', (
      select coalesce(json_agg(json_build_array(a.id, a.name, a.birth_year, a.sex) order by a.id), '[]'::json)
      from public.athletes a
      where exists (select 1 from public.results r where r.athlete_id = a.id)  -- csak a nagyatádi teljes táv
    ),
    'results', (
      select coalesce(json_agg(json_build_array(
               r.athlete_id, r.year, r.pos, r.finish_s,
               r.swim_s, r.t1_s, r.bike_s, r.t2_s, r.run_s, r.club
             ) order by r.year, r.pos), '[]'::json)
      from public.results r
    )
  );
$$;

revoke all on function public.finisher_data() from public;
grant execute on function public.finisher_data() to anon, authenticated;

-- ---------------------------------------------------------------------
-- Köztes mérőpontok (EvoChip, 2022-től): úszás körök, kerékpár
-- szakaszok, futás körök. Rajtszám + év a kulcs (ez akkor is stabil, ha a
-- névpárosítás változik); a versenyzőhöz a lap_data() rendeli hozzá.
-- laps: [[összidő_mp, nemenkénti_helyezés], ...] a lap_points sorrendjében
-- ---------------------------------------------------------------------
create table if not exists public.lap_points (
  year   smallint not null,
  idx    smallint not null,
  label  text     not null,
  disc   text     not null check (disc in ('swim', 'tr', 'bike', 'run')),
  km     real,
  primary key (year, idx)
);

create table if not exists public.result_laps (
  year   smallint not null,
  bib    integer  not null,
  laps   jsonb    not null,
  primary key (year, bib)
);

alter table public.lap_points  enable row level security;
alter table public.result_laps enable row level security;

drop policy if exists "lap_points: public read" on public.lap_points;
create policy "lap_points: public read" on public.lap_points for select to anon, authenticated using (true);

drop policy if exists "result_laps: public read" on public.result_laps;
create policy "result_laps: public read" on public.result_laps for select to anon, authenticated using (true);

revoke insert, update, delete, truncate on public.lap_points, public.result_laps from anon, authenticated;
grant select on public.lap_points, public.result_laps to anon, authenticated;

-- Egy év összes köztes adata (a mezőny mediánjához is kell), versenyzőnként.
create or replace function public.lap_data(p_year integer)
returns json
language sql
stable
security invoker
set search_path = public
as $$
  select json_build_object(
    'year', p_year,
    'points', (
      select coalesce(json_agg(json_build_object('label', p.label, 'disc', p.disc, 'km', p.km) order by p.idx), '[]'::json)
      from public.lap_points p where p.year = p_year
    ),
    'athletes', (
      select coalesce(json_object_agg(r.athlete_id::text, l.laps), '{}'::json)
      from public.result_laps l
      join public.results r on r.year = l.year and r.bib = l.bib
      where l.year = p_year
    )
  );
$$;

revoke all on function public.lap_data(integer) from public;
grant execute on function public.lap_data(integer) to anon, authenticated;

-- ---------------------------------------------------------------------
-- További eXtremeMan versenyek (Kaposvár, Gyékényes, Balatonszemes, Tab,
-- Velence, Székesfehérvár, Nágocs, Nagyatád többi táva ...), 2015-től.
-- ---------------------------------------------------------------------
create table if not exists public.races (
  key          text primary key,            -- pl. 2026-gyekenyes-t51
  year         smallint not null,
  series       text not null,               -- pl. gyekenyes
  series_name  text not null,               -- pl. Gyékényes
  name         text not null,               -- pl. eXtremeMan 51.5
  seg_labels   jsonb not null default '[]', -- a szakaszok nevei, pl. ["Úszás","Depó 1",...]
  n            integer not null default 0,  -- célba érkezők
  best_s       integer,
  median_s     integer
);

create table if not exists public.race_results (
  race_key    text    not null references public.races(key) on delete cascade,
  athlete_id  integer not null references public.athletes(id) on delete cascade,
  pos         integer,                      -- abszolút helyezés (idő szerint)
  sex_rank    integer,
  finish_s    integer not null,
  segs        jsonb   not null default '[]',-- szakaszidők mp-ben, a seg_labels sorrendjében
  club        text,
  primary key (race_key, athlete_id)
);
create index if not exists race_results_athlete_idx on public.race_results (athlete_id);

alter table public.races        enable row level security;
alter table public.race_results enable row level security;
drop policy if exists "races: public read" on public.races;
create policy "races: public read" on public.races for select to anon, authenticated using (true);
drop policy if exists "race_results: public read" on public.race_results;
create policy "race_results: public read" on public.race_results for select to anon, authenticated using (true);
revoke insert, update, delete, truncate on public.races, public.race_results from anon, authenticated;
grant select on public.races, public.race_results to anon, authenticated;

-- Az összes további verseny egy hívással (a versenyző- és versenyoldalak töltik be,
-- igény szerint). Formátum = data/other.json.
create or replace function public.other_data()
returns json
language sql
stable
security invoker
set search_path = public
as $$
  with rr as (select key as race_key, row_number() over (order by year, key) - 1 as idx from public.races)
  select json_build_object(
    'races', (
      select coalesce(json_agg(json_build_array(r.key, r.year, r.series, r.series_name, r.name, r.seg_labels, r.n, r.best_s, r.median_s)
                               order by r.year, r.key), '[]'::json)
      from public.races r
    ),
    'athletes', (
      select coalesce(json_agg(json_build_array(a.id, a.name, a.birth_year, a.sex) order by a.id), '[]'::json)
      from public.athletes a
      where not exists (select 1 from public.results r where r.athlete_id = a.id)
    ),
    'results', (
      select coalesce(json_agg(json_build_array(rr.idx, x.athlete_id, x.pos, x.sex_rank, x.finish_s, x.segs, x.club)
                               order by rr.idx, x.pos), '[]'::json)
      from public.race_results x join rr on rr.race_key = x.race_key
    )
  );
$$;
revoke all on function public.other_data() from public;
grant execute on function public.other_data() to anon, authenticated;
