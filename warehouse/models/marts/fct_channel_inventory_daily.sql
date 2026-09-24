-- Implied channel stock per distributor x sku x day (PLAN §7 channel_days_of_stock, decisions D5/D10/D13):
--   stock_units    = opening stock + cumulative primary receipts - cumulative reported secondary (units)
--   days_of_stock  = stock_units / avg daily secondary over the trailing 30 days (fewer at the window start,
--                    minimum 14); null when there were no secondary sales in that period.
-- Rows exist for every pair that ever held stock, from its first day through the as-of date.
{{ config(
    post_hook="{{ apply_region_rls() }}",
    indexes=[{'columns': ['distributor_id', 'sku', 'date_day']}, {'columns': ['date_day']}]
) }}

with primary_daily as (
    select distributor_id, sku, invoice_date as flow_date, sum(qty) as units
    from {{ ref('fct_primary_sales') }}
    group by distributor_id, sku, invoice_date
),

secondary_daily as (
    select distributor_id, sku, sale_date as flow_date, sum(qty) as units
    from {{ ref('stg_secondary_sales') }}
    group by distributor_id, sku, sale_date
),

opening as (
    select distributor_id, sku, opening_qty
    from {{ ref('stg_opening_channel_stock') }}
),

pairs as (
    select distributor_id, sku, min(start_date) as start_date
    from (
        select distributor_id, sku, '{{ var("window_start") }}'::date as start_date from opening
        union all
        select distributor_id, sku, min(flow_date) from primary_daily group by distributor_id, sku
    ) as starts
    group by distributor_id, sku
),

flows as (
    select
        pr.distributor_id,
        pr.sku,
        c.date_day,
        coalesce(pd.units, 0) as primary_units,
        coalesce(sd.units, 0) as secondary_units
    from pairs as pr
    inner join {{ ref('int_calendar') }} as c on c.date_day >= pr.start_date
    left join primary_daily as pd
        on pd.distributor_id = pr.distributor_id and pd.sku = pr.sku and pd.flow_date = c.date_day
    left join secondary_daily as sd
        on sd.distributor_id = pr.distributor_id and sd.sku = pr.sku and sd.flow_date = c.date_day
),

running as (
    select
        f.distributor_id,
        f.sku,
        f.date_day,
        f.primary_units,
        f.secondary_units,
        coalesce(o.opening_qty, 0) + sum(f.primary_units - f.secondary_units) over w as stock_units,
        sum(f.secondary_units) over (w rows between 29 preceding and current row) as secondary_units_t30,
        least(row_number() over w, 30) as t30_days_available
    from flows as f
    left join opening as o on o.distributor_id = f.distributor_id and o.sku = f.sku
    window w as (partition by f.distributor_id, f.sku order by f.date_day)
),

rated as (
    select
        *,
        case
            when t30_days_available >= 14 and secondary_units_t30 > 0
                then round(secondary_units_t30::numeric / t30_days_available, 4)
        end as avg_daily_secondary_units
    from running
)

select
    r.date_day,
    r.distributor_id,
    d.region,
    d.state,
    d.tier,
    r.sku,
    p.category,
    r.primary_units,
    r.secondary_units,
    r.stock_units,
    r.secondary_units_t30,
    r.avg_daily_secondary_units,
    round(r.stock_units / r.avg_daily_secondary_units, 1) as days_of_stock,
    r.stock_units / r.avg_daily_secondary_units < {{ var('dos_stockout_below') }} as is_stockout,
    r.stock_units / r.avg_daily_secondary_units > {{ var('dos_overstock_above') }} as is_overstock,
    r.date_day <= run.as_of_date - {{ var('secondary_horizon_days') }} as is_settled
from rated as r
inner join {{ ref('dim_distributor') }} as d on d.distributor_id = r.distributor_id
inner join {{ ref('stg_products') }} as p on p.sku = r.sku
cross join {{ ref('stg_generation_run') }} as run
