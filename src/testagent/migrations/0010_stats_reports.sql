-- M1-11: defect statistics views (rejected defects excluded, severity-weighted) and report
-- provenance. Version scope; the service applies the same rules with time/task-run filters.
ALTER TABLE report
  ADD COLUMN agent_run_id uuid REFERENCES agent_run(id),
  ADD COLUMN created_by text;

CREATE VIEW v_defect_by_requirement AS
WITH d AS (
  SELECT dr.requirement_id, df.id, df.severity, w.weight
  FROM defect_requirement dr
  JOIN defect df ON df.id = dr.defect_id AND df.status <> 'rejected'
  JOIN severity_weight w ON w.severity = df.severity
), sev AS (
  SELECT requirement_id, jsonb_object_agg(severity, n) AS by_severity
  FROM (SELECT requirement_id, severity, count(*) AS n FROM d GROUP BY 1, 2) x
  GROUP BY requirement_id
), ex AS (
  SELECT l.requirement_id, count(DISTINCT e.case_id) AS executed_cases
  FROM case_requirement_link l
  JOIN case_execution e ON e.case_id = l.case_id AND e.status IN ('passed', 'failed', 'error')
  GROUP BY l.requirement_id
)
SELECT r.id AS requirement_id, r.version_id,
       count(DISTINCT d.id) AS defect_count,
       COALESCE(sum(d.weight), 0) AS weighted_score,
       COALESCE(max(ex.executed_cases), 0) AS executed_cases,
       CASE WHEN COALESCE(max(ex.executed_cases), 0) = 0 THEN NULL
            ELSE count(DISTINCT d.id)::numeric / max(ex.executed_cases) END AS density,
       COALESCE(max(sev.by_severity::text)::jsonb, '{}'::jsonb) AS by_severity
FROM requirement r
LEFT JOIN d ON d.requirement_id = r.id
LEFT JOIN ex ON ex.requirement_id = r.id
LEFT JOIN sev ON sev.requirement_id = r.id
GROUP BY r.id, r.version_id;

CREATE VIEW v_defect_by_person AS
WITH live AS (
  SELECT df.id, df.version_id, w.weight
  FROM defect df JOIN severity_weight w ON w.severity = df.severity
  WHERE df.status <> 'rejected'
), attributed AS (
  SELECT x.person_id, l.version_id, count(DISTINCT l.id) AS attributed_count,
         sum(l.weight) AS attributed_score
  FROM (SELECT DISTINCT defect_id, person_id FROM defect_responsible) x
  JOIN live l ON l.id = x.defect_id
  GROUP BY x.person_id, l.version_id
), by_role AS (
  SELECT person_id, version_id,
         jsonb_object_agg(role, jsonb_build_object('count', n, 'score', s)) AS attributed_by_role
  FROM (SELECT x.person_id, l.version_id, x.role, count(*) AS n, sum(l.weight) AS s
        FROM defect_responsible x JOIN live l ON l.id = x.defect_id
        GROUP BY 1, 2, 3) y
  GROUP BY person_id, version_id
), related AS (
  SELECT rp.person_id, l.version_id, count(DISTINCT l.id) AS related_count,
         jsonb_agg(DISTINCT r.code) AS requirements
  FROM live l
  JOIN defect_requirement dr ON dr.defect_id = l.id
  JOIN requirement r ON r.id = dr.requirement_id
  JOIN requirement_person rp ON rp.requirement_id = dr.requirement_id
  GROUP BY rp.person_id, l.version_id
)
SELECT p.id AS person_id, k.version_id,
       COALESCE(a.attributed_count, 0) AS attributed_count,
       COALESCE(a.attributed_score, 0) AS attributed_score,
       COALESCE(b.attributed_by_role, '{}'::jsonb) AS attributed_by_role,
       COALESCE(rl.related_count, 0) AS related_count,
       COALESCE(rl.requirements, '[]'::jsonb) AS requirements
FROM person p
JOIN (SELECT person_id, version_id FROM attributed
      UNION SELECT person_id, version_id FROM related) k ON k.person_id = p.id
LEFT JOIN attributed a ON a.person_id = p.id AND a.version_id IS NOT DISTINCT FROM k.version_id
LEFT JOIN by_role b ON b.person_id = p.id AND b.version_id IS NOT DISTINCT FROM k.version_id
LEFT JOIN related rl ON rl.person_id = p.id AND rl.version_id IS NOT DISTINCT FROM k.version_id;
