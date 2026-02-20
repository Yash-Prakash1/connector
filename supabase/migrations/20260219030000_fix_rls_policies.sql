-- Drop and recreate RLS policies to ensure they're applied correctly

DROP POLICY IF EXISTS "anon_insert_contributions" ON contributions;
DROP POLICY IF EXISTS "anon_select_resolution_patterns" ON resolution_patterns;
DROP POLICY IF EXISTS "anon_select_error_resolutions" ON error_resolutions;
DROP POLICY IF EXISTS "anon_select_working_configurations" ON working_configurations;

-- Allow anyone (anon + authenticated) to INSERT contributions
CREATE POLICY "allow_insert_contributions"
    ON contributions FOR INSERT
    WITH CHECK (true);

-- Allow anyone to SELECT from read tables
CREATE POLICY "allow_select_resolution_patterns"
    ON resolution_patterns FOR SELECT
    USING (true);

CREATE POLICY "allow_select_error_resolutions"
    ON error_resolutions FOR SELECT
    USING (true);

CREATE POLICY "allow_select_working_configurations"
    ON working_configurations FOR SELECT
    USING (true);

-- Ensure privileges are granted
GRANT INSERT ON contributions TO anon, authenticated;
GRANT SELECT ON resolution_patterns TO anon, authenticated;
GRANT SELECT ON error_resolutions TO anon, authenticated;
GRANT SELECT ON working_configurations TO anon, authenticated;
