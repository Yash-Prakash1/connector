-- Grant base table privileges to anon role (RLS policies alone aren't enough)

GRANT INSERT ON contributions TO anon;
GRANT SELECT ON resolution_patterns TO anon;
GRANT SELECT ON error_resolutions TO anon;
GRANT SELECT ON working_configurations TO anon;
