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
