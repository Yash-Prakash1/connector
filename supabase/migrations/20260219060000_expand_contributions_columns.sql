-- Add columns to contributions to capture all metadata from _push_contribution

ALTER TABLE contributions
    ADD COLUMN IF NOT EXISTS os_version text,
    ADD COLUMN IF NOT EXISTS initial_state_fingerprint text,
    ADD COLUMN IF NOT EXISTS outcome text,
    ADD COLUMN IF NOT EXISTS total_steps integer,
    ADD COLUMN IF NOT EXISTS agent_version text;
