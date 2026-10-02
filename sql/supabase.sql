-- Run once in a NEW Supabase project. Do not apply over v1 tables.
begin;
create table if not exists public.stations (
 station_key text primary key, name text, province_code text, district_code text);
create table if not exists public.observations (
 station_key text not null references public.stations(station_key), observed_at timestamptz not null,
 level_msl double precision, level_m double precision, situation double precision,
 primary key(station_key,observed_at));
create table if not exists public.state(key text primary key,value jsonb not null);
alter table public.stations enable row level security;
alter table public.observations enable row level security;
alter table public.state enable row level security;
revoke all on public.stations,public.observations,public.state from anon,authenticated;
grant all on public.stations,public.observations,public.state to service_role;
create or replace view public.latest_water with (security_invoker=true) as
 select distinct on (o.station_key) o.*,s.name,s.province_code
 from public.observations o join public.stations s using(station_key)
 order by o.station_key,o.observed_at desc;
revoke all on public.latest_water from anon,authenticated;
grant select on public.latest_water to service_role;
create or replace function public.ingest_water(p_stations jsonb,p_observations jsonb)
returns void language plpgsql security invoker set search_path=public as $$
begin
 insert into stations select * from jsonb_to_recordset(p_stations)
 as x(station_key text,name text,province_code text,district_code text)
 on conflict(station_key) do update set name=excluded.name,province_code=excluded.province_code,
 district_code=excluded.district_code;
 insert into observations select * from jsonb_to_recordset(p_observations)
 as x(station_key text,observed_at timestamptz,level_msl double precision,level_m double precision,situation double precision)
 on conflict(station_key,observed_at) do update set level_msl=excluded.level_msl,
 level_m=excluded.level_m,situation=excluded.situation;
end $$;
revoke all on function public.ingest_water(jsonb,jsonb) from public,anon,authenticated;
grant execute on function public.ingest_water(jsonb,jsonb) to service_role;
commit;

-- Version 3 additions; safe after the matching v2 station/observation schema.
begin;
create table if not exists public.reports (
 id uuid primary key, owner_id text not null,
 category text not null check(category in ('flood','blocked_canal','gate','other')),
 description text not null check(char_length(description) between 10 and 1000),
 latitude double precision, longitude double precision,
 photo_path text, status text not null default 'new' check(status in ('new','reviewing','resolved')),
 consent_version text not null default '2026-10-02',
 created_at timestamptz not null default now(),
 check ((latitude is null and longitude is null) or (latitude between -90 and 90 and longitude between -180 and 180))
);
create index if not exists reports_owner_time on public.reports(owner_id,created_at desc);
create index if not exists reports_time on public.reports(created_at);
create table if not exists public.line_events(id text primary key, created_at timestamptz not null default now(),reply_status text not null default 'claimed');
alter table public.reports enable row level security;
alter table public.line_events enable row level security;
revoke all on public.reports,public.line_events from public,anon,authenticated;
grant all on public.reports,public.line_events to service_role;
create or replace function public.create_water_report(p_id uuid,p_owner text,p_category text,p_description text,p_lat double precision,p_lon double precision)
returns jsonb language plpgsql security invoker set search_path=public as $$
declare existing reports%rowtype; result reports%rowtype;
begin
 perform pg_advisory_xact_lock(87312003);
 select * into existing from reports where id=p_id;
 if found then
  if existing.owner_id<>p_owner then raise exception 'FORBIDDEN'; end if;
  return to_jsonb(existing);
 end if;
 -- Hard pilot caps, checked in one transaction for concurrent requests.
 if (select count(*) from reports where owner_id=p_owner and created_at >= date_trunc('day',now() at time zone 'Asia/Bangkok') at time zone 'Asia/Bangkok') >= 3
 or (select count(*) from reports where created_at >= date_trunc('month',now() at time zone 'Asia/Bangkok') at time zone 'Asia/Bangkok') >= 100 then
  raise exception 'REPORT_LIMIT';
 end if;
 insert into reports(id,owner_id,category,description,latitude,longitude)
 values(p_id,p_owner,p_category,p_description,p_lat,p_lon) returning * into result;
 return to_jsonb(result);
end $$;
revoke all on function public.create_water_report(uuid,text,text,text,double precision,double precision) from public,anon,authenticated;
grant execute on function public.create_water_report(uuid,text,text,text,double precision,double precision) to service_role;
create or replace function public.claim_line_event(p_id text)
returns boolean language plpgsql security invoker set search_path=public as $$
declare n integer;
begin
 insert into line_events(id) values(p_id) on conflict do nothing;
 get diagnostics n=row_count;
 return n=1;
end $$;
revoke all on function public.claim_line_event(text) from public,anon,authenticated;
grant execute on function public.claim_line_event(text) to service_role;
commit;
