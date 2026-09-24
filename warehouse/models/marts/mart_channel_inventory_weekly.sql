-- Serving grain for the governed channel-inventory metrics (decisions D24): one row per distributor x sku x ISO week.
-- The stock snapshot is the last available day of the week (the as-of date for the week in progress), and the
-- day counts keep stockout_rate / overstock_rate exact as "% of distributor-SKU-days". The daily detail stays in
-- fct_channel_inventory_daily; at 6.5M rows its last-day-of-period queries were too slow for the API's 5 s budget.
{{ config(
    post_hook="{{ apply_region_rls(via_distributor=true) }}",
    indexes=[{'columns': ['week_start']}, {'columns': ['distributor_id', 'week_start']}]
) }}
-- depends_on: {{ ref('dim_distributor') }}

with daily as (
    select
        distributor_id,
        sku,
        date_trunc('week', date_day)::date as week_start,
        date_day,
        stock_units,
        avg_daily_secondary_units,
        days_of_stock,
        is_stockout,
        is_overstock
    from {{ ref('fct_channel_inventory_daily') }}
),

snapshots as (
    select distinct on (distributor_id, sku, week_start)
        distributor_id,
        sku,
        week_start,
        date_day as snapshot_date,
        stock_units,
        avg_daily_secondary_units,
        days_of_stock
    from daily
    order by distributor_id, sku, week_start, date_day desc
),

day_counts as (
    select
        distributor_id,
        sku,
        week_start,
        count(*) filter (where days_of_stock is not null)::integer as days_measured,
        count(*) filter (where is_stockout)::integer as stockout_days,
        count(*) filter (where is_overstock)::integer as overstock_days
    from daily
    group by distributor_id, sku, week_start
)

select
    s.week_start,
    s.snapshot_date,
    s.distributor_id,
    s.sku,
    s.stock_units,
    s.avg_daily_secondary_units,
    s.days_of_stock,
    c.days_measured,
    c.stockout_days,
    c.overstock_days
from snapshots as s
inner join day_counts as c
    on c.distributor_id = s.distributor_id and c.sku = s.sku and c.week_start = s.week_start
