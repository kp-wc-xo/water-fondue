-- READ ONLY: use Supabase dashboard Usage for authoritative plan measurements.
select pg_size_pretty(pg_database_size(current_database())) as database_size;
select count(*) as report_count from public.reports;
select reply_status,count(*) from public.line_events group by reply_status;
select id,created_at from public.reports order by created_at desc limit 10;
-- Manual maintenance only after backup and operator review:
-- delete from public.line_events where created_at < now() - interval '30 days';
-- Reports and photos have NO automated deletion: follow the privacy/retention guide.
