-- Ensure anon has full access path: schema usage + table privileges + RLS

-- Schema-level access
GRANT USAGE ON SCHEMA public TO anon;
GRANT USAGE ON SCHEMA public TO authenticated;

-- Table-level privileges
GRANT ALL ON contributions TO anon;
GRANT SELECT ON resolution_patterns TO anon;
GRANT SELECT ON error_resolutions TO anon;
GRANT SELECT ON working_configurations TO anon;

-- Drop all existing policies on contributions and recreate
DROP POLICY IF EXISTS "allow_insert_contributions" ON contributions;
DROP POLICY IF EXISTS "anon_insert_contributions" ON contributions;

-- Use permissive policy (default) for all roles
CREATE POLICY "contributions_insert_policy"
    ON contributions
    FOR INSERT
    TO public
    WITH CHECK (true);

-- Also add a SELECT policy for contributions so we can verify data
CREATE POLICY "contributions_select_policy"
    ON contributions
    FOR SELECT
    TO public
    USING (true);
