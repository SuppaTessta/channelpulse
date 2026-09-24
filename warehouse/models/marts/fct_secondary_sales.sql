-- Distributor -> retailer sell-out as reported (re-sent uploads removed in staging).
-- secondary_sales_value = sum(secondary_value_inr), priced at the current list price (PLAN §7).
{{ config(
    post_hook="{{ apply_region_rls() }}",
    indexes=[{'columns': ['distributor_id', 'sale_date']}, {'columns': ['sale_date']}]
) }}

select
    s.record_id,
    s.distributor_id,
    d.region,
    d.state,
    d.district,
    d.tier,
    s.retailer_id,
    s.sku,
    p.category,
    s.sale_date,
    s.reported_date,
    s.reported_date - s.sale_date as reporting_lag_days,
    s.report_source,
    s.qty,
    p.list_price_inr,
    (s.qty * p.list_price_inr)::numeric(14, 2) as secondary_value_inr,
    -- D12: sale dates inside the reporting horizon are still filling in
    s.sale_date <= run.as_of_date - {{ var('secondary_horizon_days') }} as is_settled
from {{ ref('stg_secondary_sales') }} as s
inner join {{ ref('dim_distributor') }} as d on d.distributor_id = s.distributor_id
inner join {{ ref('stg_products') }} as p on p.sku = s.sku
cross join {{ ref('stg_generation_run') }} as run
