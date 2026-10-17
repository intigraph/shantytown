WITH kinds(kind) AS (
    VALUES ('input_uncached'), ('cache_read_input'), ('cache_write_input'), ('output')
), daily AS (
    SELECT agent, day, kind,
           CASE WHEN count(value) = count(*) THEN sum(value) END AS tokens_observed,
           count(*) AS observed_groups
    FROM usage GROUP BY agent, day, kind
), retained AS (
    SELECT agent_iri, day, count(DISTINCT item_iri) AS retained_closes
    FROM closes GROUP BY agent_iri, day
)
SELECT a.iri AS agent_iri, strftime(d.day, '%Y-%m-%d') AS day, k.kind,
       u.tokens_observed, coalesce(u.observed_groups, 0) AS observed_groups,
       false AS usage_day_complete,
       coalesce(c.retained_closes, 0) AS retained_closes_current_assignee
FROM agents a CROSS JOIN days d CROSS JOIN kinds k
LEFT JOIN daily u ON u.agent = a.label AND u.day = d.day AND u.kind = k.kind
LEFT JOIN retained c ON c.agent_iri = a.iri AND c.day = d.day
ORDER BY a.iri, d.day, k.kind;
