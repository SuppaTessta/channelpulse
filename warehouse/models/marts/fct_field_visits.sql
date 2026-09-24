-- Sales-rep visits to distributors (PLAN §9 Distributor 360 "visit history"; health-score visit recency). RLS by region.
{{ config(
    post_hook="{{ apply_region_rls() }}",
    indexes=[{'columns': ['distributor_id', 'visit_date']}]
) }}

select
    v.visit_id,
    v.distributor_id,
    d.region,
    d.state,
    v.rep_id,
    r.rep_name,
    v.visit_date,
    v.is_geofence_verified,
    v.visit_notes
from {{ ref('stg_field_visits') }} as v
inner join {{ ref('dim_distributor') }} as d on d.distributor_id = v.distributor_id
left join {{ ref('stg_sales_reps') }} as r on r.rep_id = v.rep_id
