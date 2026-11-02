-- User decision (2026-10-31): default severity weights are critical 10 / major 3 / minor 1 / trivial 0.1.
-- Only replace the previous defaults (5/3/1/0.5) when they are still untouched; customised weights stay.
UPDATE severity_weight sw SET weight = v.weight
FROM (VALUES ('critical', 10), ('major', 3), ('minor', 1), ('trivial', 0.1)) AS v(severity, weight)
WHERE sw.severity = v.severity
  AND (SELECT count(*) FROM severity_weight o
       WHERE (o.severity, o.weight) IN (('critical', 5), ('major', 3), ('minor', 1), ('trivial', 0.5))) = 4;
