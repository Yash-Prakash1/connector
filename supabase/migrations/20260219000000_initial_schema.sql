-- Hardware Connector — Supabase schema
-- Apply via: Supabase Dashboard → SQL Editor → paste & run
--
-- Four tables:
--   contributions        — raw session data pushed by clients (INSERT only)
--   resolution_patterns  — aggregated patterns (SELECT only, written by trigger)
--   error_resolutions    — stub for MVP (SELECT only, empty)
--   working_configurations — stub for MVP (SELECT only, empty)

-- ── contributions ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS contributions (
    id              uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    device_type     text NOT NULL,
    os              text NOT NULL,
    success         boolean NOT NULL,
    steps           jsonb NOT NULL DEFAULT '[]',
    environment     jsonb NOT NULL DEFAULT '{}',
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_contributions_device_os
    ON contributions (device_type, os);

-- ── resolution_patterns ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS resolution_patterns (
    id                          text PRIMARY KEY,
    device_type                 text NOT NULL,
    os                          text NOT NULL,
    initial_state_fingerprint   text,
    steps                       jsonb NOT NULL DEFAULT '[]',
    success_count               integer NOT NULL DEFAULT 0,
    fail_count                  integer NOT NULL DEFAULT 0,
    success_rate                double precision NOT NULL DEFAULT 0,
    confidence_score            double precision NOT NULL DEFAULT 0,
    created_at                  timestamptz NOT NULL DEFAULT now(),
    updated_at                  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_resolution_patterns_device_os
    ON resolution_patterns (device_type, os);

-- ── error_resolutions (stub) ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS error_resolutions (
    id                  uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    device_type         text,
    os                  text,
    error_fingerprint   text,
    error_category      text,
    explanation         text,
    resolution_action   text,
    resolution_detail   jsonb NOT NULL DEFAULT '{}',
    success_count       integer NOT NULL DEFAULT 0,
    success_rate        double precision NOT NULL DEFAULT 0,
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- ── working_configurations (stub) ────────────────────────────────────

CREATE TABLE IF NOT EXISTS working_configurations (
    id              uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    device_type     text NOT NULL,
    os              text NOT NULL,
    configuration   jsonb NOT NULL DEFAULT '{}',
    verified_count  integer NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- ── Trigger: auto-aggregate contributions → resolution_patterns ──────
--
-- Deterministic pattern ID = md5(device_type || os || steps::text)
-- so identical step sequences always map to the same row.

CREATE OR REPLACE FUNCTION aggregate_contribution()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    pattern_id text;
BEGIN
    pattern_id := md5(NEW.device_type || NEW.os || NEW.steps::text);

    INSERT INTO resolution_patterns (
        id, device_type, os, steps,
        success_count, fail_count, success_rate, confidence_score
    )
    VALUES (
        pattern_id,
        NEW.device_type,
        NEW.os,
        NEW.steps,
        CASE WHEN NEW.success THEN 1 ELSE 0 END,
        CASE WHEN NEW.success THEN 0 ELSE 1 END,
        CASE WHEN NEW.success THEN 1.0 ELSE 0.0 END,
        1  -- confidence_score = total attempts
    )
    ON CONFLICT (id) DO UPDATE SET
        success_count    = resolution_patterns.success_count
                           + CASE WHEN NEW.success THEN 1 ELSE 0 END,
        fail_count       = resolution_patterns.fail_count
                           + CASE WHEN NEW.success THEN 0 ELSE 1 END,
        success_rate     = (resolution_patterns.success_count
                            + CASE WHEN NEW.success THEN 1 ELSE 0 END)::double precision
                           / (resolution_patterns.success_count
                              + resolution_patterns.fail_count + 1)::double precision,
        confidence_score = resolution_patterns.success_count
                           + resolution_patterns.fail_count + 1,
        updated_at       = now();

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_aggregate_contribution
    AFTER INSERT ON contributions
    FOR EACH ROW
    EXECUTE FUNCTION aggregate_contribution();

-- ── Row-Level Security ───────────────────────────────────────────────

ALTER TABLE contributions ENABLE ROW LEVEL SECURITY;
ALTER TABLE resolution_patterns ENABLE ROW LEVEL SECURITY;
ALTER TABLE error_resolutions ENABLE ROW LEVEL SECURITY;
ALTER TABLE working_configurations ENABLE ROW LEVEL SECURITY;

-- Anon can INSERT contributions
CREATE POLICY "anon_insert_contributions"
    ON contributions FOR INSERT
    TO anon
    WITH CHECK (true);

-- Anon can SELECT resolution_patterns
CREATE POLICY "anon_select_resolution_patterns"
    ON resolution_patterns FOR SELECT
    TO anon
    USING (true);

-- Anon can SELECT error_resolutions
CREATE POLICY "anon_select_error_resolutions"
    ON error_resolutions FOR SELECT
    TO anon
    USING (true);

-- Anon can SELECT working_configurations
CREATE POLICY "anon_select_working_configurations"
    ON working_configurations FOR SELECT
    TO anon
    USING (true);

-- ── Seed data ────────────────────────────────────────────────────────
-- Proven pattern: Rigol DS1054Z on Linux
-- Steps use the normalized format that the replay engine expects:
--   pip_install → system_install (target) → permission_fix (udev_rule)
--   → permission_fix (udev_reload) → verify (device_check)
-- Meets replay thresholds: ≥5 successes, ≥90% rate

INSERT INTO resolution_patterns (
    id, device_type, os, steps,
    success_count, fail_count, success_rate, confidence_score
)
VALUES (
    md5('rigol_ds1054z' || 'linux' || '[{"action":"pip_install","packages":["pyusb","pyvisa","pyvisa-py"]},{"action":"system_install","target":"libusb"},{"action":"permission_fix","pattern":"udev_rule"},{"action":"permission_fix","pattern":"udev_reload"},{"action":"verify","pattern":"device_check"}]'),
    'rigol_ds1054z',
    'linux',
    '[{"action":"pip_install","packages":["pyusb","pyvisa","pyvisa-py"]},{"action":"system_install","target":"libusb"},{"action":"permission_fix","pattern":"udev_rule"},{"action":"permission_fix","pattern":"udev_reload"},{"action":"verify","pattern":"device_check"}]'::jsonb,
    10,
    0,
    1.0,
    10
)
ON CONFLICT (id) DO NOTHING;
