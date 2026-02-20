-- Fix seed data: use normalized step format that the replay engine expects

DELETE FROM resolution_patterns WHERE id = 'ec0464bf1cf1cff14521c38d355ddf93';

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
