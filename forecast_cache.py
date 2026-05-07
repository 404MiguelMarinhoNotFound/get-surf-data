"""Neon-backed latest forecast cache."""

import json
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from uuid import uuid4

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception

import db
import explainer
import forecast_sync


try:
    LISBON_TZ = ZoneInfo("Europe/Lisbon") if ZoneInfo else None
except ZoneInfoNotFoundError:
    LISBON_TZ = None
CACHE_KEY = "global"
PAYLOAD_VERSION = 1
ADVISORY_LOCK_ID = 2026050701


def utc_now():
    return datetime.now(timezone.utc)


def _last_sunday(year, month):
    day = datetime(year, month, 28)
    while day.weekday() != 6:
        day += timedelta(days=1)
    return day.date()


def _fallback_lisbon_tz(now_utc):
    start = datetime(now_utc.year, 3, _last_sunday(now_utc.year, 3).day, 1, tzinfo=timezone.utc)
    end = datetime(now_utc.year, 10, _last_sunday(now_utc.year, 10).day, 1, tzinfo=timezone.utc)
    return timezone(timedelta(hours=1 if start <= now_utc < end else 0), "Europe/Lisbon")


def latest_lisbon_slot(now_utc=None):
    """Return the latest 00:00/12:00 Europe/Lisbon slot due at now."""
    now_utc = now_utc or utc_now()
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    local = now_utc.astimezone(LISBON_TZ or _fallback_lisbon_tz(now_utc))
    hour = 12 if local.hour >= 12 else 0
    return local.replace(hour=hour, minute=0, second=0, microsecond=0)


def is_stale(now_utc, state):
    due_slot = latest_lisbon_slot(now_utc)
    last_slot = (state or {}).get("last_success_slot_local")
    return last_slot is None or last_slot < due_slot


def empty_cache_payload(spot_id, level):
    return {
        "error": "forecast cache is empty; run scripts/db_backfill.py or /api/refresh",
        "code": "forecast_cache_empty",
        "spot_id": spot_id,
        "level": level,
    }


def _iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _lisbon_iso(value):
    if value is None:
        return None
    if not hasattr(value, "astimezone"):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(LISBON_TZ or _fallback_lisbon_tz(value.astimezone(timezone.utc))).isoformat()


def _as_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first(row, *keys):
    for key in keys:
        if row.get(key) is not None:
            return row.get(key)
    return None


def hourly_db_row(spot_id, source, run_id, row):
    return {
        "spot_id": spot_id,
        "source": source,
        "timestamp_utc": row.get("timestamp_utc"),
        "wave_height": _as_float(row.get("wave_height")),
        "wave_period": _as_float(row.get("wave_period")),
        "wave_direction": _as_float(row.get("wave_direction")),
        "swell_height": _as_float(row.get("swell_height")),
        "swell_period": _as_float(row.get("swell_period")),
        "swell_direction": _as_float(row.get("swell_direction")),
        "swell2_height": _as_float(row.get("swell2_height")),
        "swell2_period": _as_float(row.get("swell2_period")),
        "swell2_direction": _as_float(row.get("swell2_direction")),
        "wind_wave_height": _as_float(row.get("wind_wave_height")),
        "wind_speed_kmh": _as_float(_first(row, "wind_speed_kmh", "wind_speed")),
        "wind_direction_deg": _as_float(_first(row, "wind_direction_deg", "wind_direction")),
        "wind_gusts_kmh": _as_float(_first(row, "wind_gusts_kmh", "wind_gusts")),
        "tide_height_m": _as_float(row.get("tide_height_m")),
        "air_temp_c": _as_float(_first(row, "air_temp_c", "air_temp", "temperature_c")),
        "raw": dict(row),
        "run_id": run_id,
    }


def get_refresh_state(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into forecast_refresh_state (cache_key)
            values (%s)
            on conflict (cache_key) do nothing
            """,
            (CACHE_KEY,),
        )
        cur.execute(
            "select * from forecast_refresh_state where cache_key = %s",
            (CACHE_KEY,),
        )
        return cur.fetchone() or {}


def read_cached_payload(spot_id, level):
    if level not in explainer.VALID_LEVELS:
        level = explainer.DEFAULT_LEVEL
    with db.connect() as conn:
        state = get_refresh_state(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                select payload, fetched_at, updated_at
                from spot_level_snapshot
                where spot_id = %s and level = %s
                """,
                (spot_id, level),
            )
            row = cur.fetchone()
    if not row:
        return None
    payload = dict(row["payload"])
    payload["cache_status"] = state.get("status")
    payload["cache_updated_at"] = _iso(row.get("updated_at"))
    payload["cache_stale"] = is_stale(utc_now(), state)
    return payload


def _json_error(exc):
    return {
        "type": exc.__class__.__name__,
        "message": str(exc),
        "traceback": traceback.format_exc(limit=8),
    }


def _source_hourly_rows(spot_id, run_id, sources, payload):
    rows = []
    for source_name in ("om", "gfs", "ibi", "surfline", "windguru"):
        data = (sources.get(source_name) or {}).get("data") or {}
        for item in data.get("hourly", []) or []:
            if item.get("timestamp_utc"):
                rows.append(hourly_db_row(spot_id, source_name, run_id, item))
    for item in payload.get("rating_timeline", []) or []:
        if item.get("timestamp_utc"):
            rows.append(hourly_db_row(spot_id, "sf", run_id, item))
    return rows


def _source_snapshot_rows(spot_id, run_id, sources, payload):
    out = []
    analysis_keys = {
        "sf": None,
        "om": "om_analysis",
        "gfs": "gfs_analysis",
        "ibi": "ibi_analysis",
        "surfline": "surfline_analysis",
        "windguru": "windguru_analysis",
    }
    error_keys = {
        "sf": None,
        "om": "om_error",
        "gfs": "gfs_error",
        "ibi": "ibi_error",
        "surfline": "surfline_error",
        "windguru": "windguru_error",
    }
    for source_name in ("sf", "om", "gfs", "ibi", "surfline", "windguru"):
        source = sources.get(source_name) or {}
        data = source.get("data") or {}
        current = data.get("current") if isinstance(data, dict) else None
        if source_name == "sf":
            current = {
                key: payload.get(key)
                for key in (
                    "height_m",
                    "period_s",
                    "swell_direction",
                    "wind_state",
                    "wind_speed_kmh",
                    "rating",
                    "sea_temp_c",
                    "upstream_issued_at",
                )
                if payload.get(key) is not None
            }
        out.append(
            {
                "spot_id": spot_id,
                "source": source_name,
                "current_payload": current,
                "analysis_payload": payload.get(analysis_keys[source_name])
                if analysis_keys[source_name]
                else None,
                "error": source.get("error")
                or (payload.get(error_keys[source_name]) if error_keys[source_name] else None),
                "fetched_at": data.get("fetched_at") if isinstance(data, dict) else payload.get("fetched_at"),
                "model_init_utc": data.get("model_init_utc") if isinstance(data, dict) else None,
                "run_id": run_id,
            }
        )
    return out


def _window_rows(spot_id, level, run_id, payload):
    rows = []
    unified = payload.get("unified") or {}
    for window_type in ("top_windows", "predictor_windows"):
        for idx, win in enumerate(unified.get(window_type, []) or []):
            rows.append(
                {
                    "spot_id": spot_id,
                    "level": level,
                    "window_type": window_type,
                    "rank": idx,
                    "starts_at": win.get("starts_at"),
                    "ends_at": win.get("ends_at"),
                    "label": win.get("label"),
                    "score": _as_float(win.get("score")),
                    "tier": win.get("tier"),
                    "payload": win,
                    "run_id": run_id,
                }
            )
    return rows


def _insert_snapshot(cur, spot_id, level, run_id, payload):
    cur.execute(
        """
        insert into spot_level_snapshot (
          spot_id, level, payload, payload_version, run_id, fetched_at, updated_at
        )
        values (%s, %s, %s, %s, %s, coalesce(%s::timestamptz, now()), now())
        on conflict (spot_id, level) do update set
          payload = excluded.payload,
          payload_version = excluded.payload_version,
          run_id = excluded.run_id,
          fetched_at = excluded.fetched_at,
          updated_at = now()
        """,
        (
            spot_id,
            level,
            db.jsonb(payload),
            PAYLOAD_VERSION,
            run_id,
            payload.get("fetched_at"),
        ),
    )


def _replace_source_rows(cur, spot_id, run_id, sources, payload):
    cur.execute("delete from source_hourly_latest where spot_id = %s", (spot_id,))
    for row in _source_hourly_rows(spot_id, run_id, sources, payload):
        cur.execute(
            """
            insert into source_hourly_latest (
              spot_id, source, timestamp_utc, wave_height, wave_period,
              wave_direction, swell_height, swell_period, swell_direction,
              swell2_height, swell2_period, swell2_direction, wind_wave_height,
              wind_speed_kmh, wind_direction_deg, wind_gusts_kmh,
              tide_height_m, air_temp_c, raw, run_id
            )
            values (
              %(spot_id)s, %(source)s, %(timestamp_utc)s, %(wave_height)s,
              %(wave_period)s, %(wave_direction)s, %(swell_height)s,
              %(swell_period)s, %(swell_direction)s, %(swell2_height)s,
              %(swell2_period)s, %(swell2_direction)s, %(wind_wave_height)s,
              %(wind_speed_kmh)s, %(wind_direction_deg)s, %(wind_gusts_kmh)s,
              %(tide_height_m)s, %(air_temp_c)s, %(raw)s, %(run_id)s
            )
            on conflict (spot_id, source, timestamp_utc) do update set
              wave_height = excluded.wave_height,
              wave_period = excluded.wave_period,
              wave_direction = excluded.wave_direction,
              swell_height = excluded.swell_height,
              swell_period = excluded.swell_period,
              swell_direction = excluded.swell_direction,
              swell2_height = excluded.swell2_height,
              swell2_period = excluded.swell2_period,
              swell2_direction = excluded.swell2_direction,
              wind_wave_height = excluded.wind_wave_height,
              wind_speed_kmh = excluded.wind_speed_kmh,
              wind_direction_deg = excluded.wind_direction_deg,
              wind_gusts_kmh = excluded.wind_gusts_kmh,
              tide_height_m = excluded.tide_height_m,
              air_temp_c = excluded.air_temp_c,
              raw = excluded.raw,
              run_id = excluded.run_id
            """,
            {**row, "raw": db.jsonb(row["raw"])},
        )


def _replace_source_snapshots(cur, spot_id, run_id, sources, payload):
    cur.execute("delete from source_snapshot_latest where spot_id = %s", (spot_id,))
    for row in _source_snapshot_rows(spot_id, run_id, sources, payload):
        cur.execute(
            """
            insert into source_snapshot_latest (
              spot_id, source, current_payload, analysis_payload, error,
              fetched_at, model_init_utc, run_id, updated_at
            )
            values (
              %(spot_id)s, %(source)s, %(current_payload)s, %(analysis_payload)s,
              %(error)s, %(fetched_at)s, %(model_init_utc)s, %(run_id)s, now()
            )
            """,
            {
                **row,
                "current_payload": db.jsonb(row["current_payload"]),
                "analysis_payload": db.jsonb(row["analysis_payload"]),
            },
        )


def _replace_window_rows(cur, spot_id, level, run_id, payload):
    cur.execute(
        "delete from window_latest where spot_id = %s and level = %s",
        (spot_id, level),
    )
    for row in _window_rows(spot_id, level, run_id, payload):
        cur.execute(
            """
            insert into window_latest (
              spot_id, level, window_type, rank, starts_at, ends_at,
              label, score, tier, payload, run_id, updated_at
            )
            values (
              %(spot_id)s, %(level)s, %(window_type)s, %(rank)s,
              %(starts_at)s, %(ends_at)s, %(label)s, %(score)s,
              %(tier)s, %(payload)s, %(run_id)s, now()
            )
            """,
            {**row, "payload": db.jsonb(row["payload"])},
        )


def _fetch_and_build_spot(spot):
    sources = forecast_sync.fetch_sources_for_spot(spot)
    payloads = forecast_sync.build_all_level_payloads(spot, sources)
    errors = [payload.get("error") for payload in payloads.values() if payload.get("error")]
    if errors:
        raise RuntimeError(f"{spot['id']}: {errors[0]}")
    return {"spot": spot, "sources": sources, "payloads": payloads}


def _fetch_all_spots(spots):
    results = []
    with ThreadPoolExecutor(max_workers=max(1, min(4, len(spots)))) as executor:
        futures = [executor.submit(_fetch_and_build_spot, spot) for spot in spots]
        for future in as_completed(futures):
            results.append(future.result())
    return results


def refresh_cache(force=False, now_utc=None, spots=None):
    now_utc = now_utc or utc_now()
    due_slot = latest_lisbon_slot(now_utc)
    run_id = str(uuid4())
    spots = spots or forecast_sync.SPOTS

    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("select pg_try_advisory_lock(%s) as locked", (ADVISORY_LOCK_ID,))
            lock_row = cur.fetchone()
            if not lock_row or not lock_row["locked"]:
                return {"status": "locked", "run_id": None}

        try:
            state = get_refresh_state(conn)
            if not force and not is_stale(now_utc, state):
                return {
                    "status": "fresh",
                    "run_id": None,
                    "last_success_slot_local": _lisbon_iso(state.get("last_success_slot_local")),
                }

            with conn.cursor() as cur:
                cur.execute(
                    """
                    update forecast_refresh_state
                    set status = 'refreshing',
                        last_started_at = %s,
                        active_run_id = %s,
                        updated_at = now()
                    where cache_key = %s
                    """,
                    (now_utc, run_id, CACHE_KEY),
                )
            conn.commit()

            built = _fetch_all_spots(spots)

            with conn.cursor() as cur:
                for item in built:
                    spot = item["spot"]
                    spot_id = spot["id"]
                    default_payload = item["payloads"][explainer.DEFAULT_LEVEL]
                    _replace_source_rows(cur, spot_id, run_id, item["sources"], default_payload)
                    _replace_source_snapshots(cur, spot_id, run_id, item["sources"], default_payload)
                    for level, payload in item["payloads"].items():
                        _insert_snapshot(cur, spot_id, level, run_id, payload)
                        _replace_window_rows(cur, spot_id, level, run_id, payload)

                cur.execute(
                    """
                    update forecast_refresh_state
                    set status = 'success',
                        last_success_at = %s,
                        last_success_slot_local = %s,
                        active_run_id = null,
                        last_error = null,
                        updated_at = now()
                    where cache_key = %s
                    """,
                    (now_utc, due_slot, CACHE_KEY),
                )
            conn.commit()
            return {
                "status": "success",
                "run_id": run_id,
                "spots": len(built),
                "levels": len(forecast_sync.ALL_LEVELS),
                "last_success_slot_local": due_slot.isoformat(),
            }
        except Exception as exc:
            conn.rollback()
            error_payload = _json_error(exc)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update forecast_refresh_state
                    set status = 'failed',
                        active_run_id = null,
                        last_error = %s,
                        updated_at = now()
                    where cache_key = %s
                    """,
                    (db.jsonb(error_payload), CACHE_KEY),
                )
            conn.commit()
            raise
        finally:
            with conn.cursor() as cur:
                cur.execute("select pg_advisory_unlock(%s)", (ADVISORY_LOCK_ID,))
            conn.commit()
