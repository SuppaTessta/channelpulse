-- A distributor's sales rep works in the distributor's region (decisions D4).
select d.distributor_id, d.region, r.region as rep_region
from {{ ref('dim_distributor') }} as d
inner join {{ ref('stg_sales_reps') }} as r on r.rep_id = d.rep_id
where d.region is distinct from r.region
