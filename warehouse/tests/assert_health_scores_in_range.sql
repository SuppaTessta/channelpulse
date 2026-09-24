select distributor_id, week_start, health_score
from {{ ref('mart_distributor_health_weekly') }}
where health_score < 0 or health_score > 100
