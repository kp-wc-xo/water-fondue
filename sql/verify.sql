-- Run in Supabase SQL Editor after first successful collection.
select count(*) as stations from public.stations;
select count(*) as observations, min(observed_at), max(observed_at) from public.observations;
select * from public.latest_water order by station_key;
select value from public.state where key='last_success';
select pg_size_pretty(pg_database_size(current_database())) as database_size;
select relname, relrowsecurity from pg_class where oid in
 ('public.stations'::regclass,'public.observations'::regclass,'public.state'::regclass);
select has_table_privilege('anon','public.observations','select') as anon_can_read,
 has_table_privilege('anon','public.observations','insert') as anon_can_insert;
