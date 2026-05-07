create table if not exists forecast_refresh_state (
  cache_key text primary key default 'global',
  last_success_at timestamptz,
  last_success_slot_local timestamptz,
  last_started_at timestamptz,
  status text not null default 'empty',
  active_run_id uuid,
  last_error jsonb,
  updated_at timestamptz not null default now()
);

insert into forecast_refresh_state (cache_key)
values ('global')
on conflict (cache_key) do nothing;

create table if not exists spot_level_snapshot (
  spot_id text not null,
  level text not null,
  payload jsonb not null,
  payload_version int not null default 1,
  run_id uuid not null,
  fetched_at timestamptz not null,
  updated_at timestamptz not null default now(),
  primary key (spot_id, level)
);

create table if not exists source_snapshot_latest (
  spot_id text not null,
  source text not null,
  current_payload jsonb,
  analysis_payload jsonb,
  error text,
  fetched_at timestamptz,
  model_init_utc timestamptz,
  run_id uuid not null,
  updated_at timestamptz not null default now(),
  primary key (spot_id, source)
);

create table if not exists source_hourly_latest (
  spot_id text not null,
  source text not null,
  timestamp_utc timestamptz not null,
  wave_height numeric(6,2),
  wave_period numeric(5,1),
  wave_direction numeric(5,1),
  swell_height numeric(6,2),
  swell_period numeric(5,1),
  swell_direction numeric(5,1),
  swell2_height numeric(6,2),
  swell2_period numeric(5,1),
  swell2_direction numeric(5,1),
  wind_wave_height numeric(6,2),
  wind_speed_kmh numeric(6,2),
  wind_direction_deg numeric(5,1),
  wind_gusts_kmh numeric(6,2),
  tide_height_m numeric(6,2),
  air_temp_c numeric(5,1),
  raw jsonb not null default '{}'::jsonb,
  run_id uuid not null,
  primary key (spot_id, source, timestamp_utc)
);

create table if not exists window_latest (
  spot_id text not null,
  level text not null,
  window_type text not null,
  rank int not null,
  starts_at timestamptz,
  ends_at timestamptz,
  label text,
  score numeric(5,2),
  tier text,
  payload jsonb not null,
  run_id uuid not null,
  updated_at timestamptz not null default now(),
  primary key (spot_id, level, window_type, rank)
);

create index if not exists spot_level_snapshot_updated_at_idx
  on spot_level_snapshot (updated_at);

create index if not exists source_hourly_latest_lookup_idx
  on source_hourly_latest (spot_id, source, timestamp_utc);

create index if not exists window_latest_lookup_idx
  on window_latest (spot_id, level, window_type, rank);
