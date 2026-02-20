-- Remove test contributions and their auto-generated patterns
-- Keep only the original seed pattern

DELETE FROM contributions;
DELETE FROM resolution_patterns
    WHERE id != '47714719ce0bcbe9cbfbdc3ed805c4c8';
