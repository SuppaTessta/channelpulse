-- Quarter-end scheme participation per distributor x scheme window x category (PLAN §7 scheme_concentration_ratio;
-- detectors/detectors.yaml `stuffing`, pre-registered):
--   rate_ratio          = window daily primary units / daily primary units over [start - 90, start - 1]
--   window_share        = share of the fiscal quarter's primary units booked in the window (its last 15 days)
--   concentration_ratio = window_share / own baseline share (leave-one-out median of the distributor's other
--                         quarters, floored at 15/91)
--   dos_excess_60d      = mean channel days of stock over QE+1..QE+60 minus the median over [start - 90, start - 1]
--   post_rate_ratio     = daily primary units over QE+1..QE+30 / daily primary units over [start - 90, start - 1]
-- Flags: is_stuffing_flag is v1 (rate_ratio >= 2.0). v2 (decisions D46) adds is_stuffing_flag_v2, provisional at
-- the window's end (v1 and at least one scheme invoice in the window), and is_stuffing_confirmed_v2 once the 60 days
-- after quarter-end are in (v2 and either orders below the baseline rate for 30 days or a 3-day stock excess).
{{ config(post_hook="{{ apply_region_rls() }}") }}

with run as (
    select as_of_date from {{ ref('stg_generation_run') }}
),

windows as (
    select distinct
        start_date,
        end_date,
        applies_to_category as category,
        date_trunc('quarter', end_date)::date as quarter_start,
        (date_trunc('quarter', end_date) + interval '3 months' - interval '1 day')::date as quarter_end,
        'FY' || right((extract(year from end_date)::int + (extract(month from end_date) >= 4)::int)::text, 2)
            || 'Q' || (((extract(month from end_date)::int + 8) % 12) / 3 + 1) as fiscal_quarter_label
    from {{ ref('stg_schemes') }}
),

eligible as (   -- needs a full 90-day baseline
    select d.distributor_id, d.region, d.tier, w.*
    from {{ ref('dim_distributor') }} as d
    cross join windows as w
    where d.first_invoice_date <= w.start_date - 90
),

primary_daily as (
    select
        distributor_id,
        category,
        invoice_date,
        sum(qty) as units,
        count(distinct invoice_id) filter (where is_scheme_invoice) as scheme_invoices,
        coalesce(sum(qty) filter (where is_scheme_invoice), 0) as scheme_units
    from {{ ref('fct_primary_sales') }}
    group by distributor_id, category, invoice_date
),

volumes as (
    select
        e.distributor_id,
        e.region,
        e.tier,
        e.category,
        e.fiscal_quarter_label,
        e.start_date,
        e.end_date,
        e.quarter_start,
        e.quarter_end,
        least(e.end_date, run.as_of_date) - e.start_date + 1 as window_days_observed,
        coalesce(sum(p.units) filter (where p.invoice_date between e.start_date and e.end_date), 0) as window_units,
        coalesce(sum(p.units) filter (where p.invoice_date between e.start_date - 90 and e.start_date - 1), 0) as baseline_units,
        coalesce(sum(p.units) filter (where p.invoice_date between e.quarter_start and e.quarter_end), 0) as quarter_units,
        coalesce(sum(p.scheme_invoices) filter (where p.invoice_date between e.start_date and e.end_date), 0) as scheme_invoices,
        coalesce(sum(p.scheme_units) filter (where p.invoice_date between e.start_date and e.end_date), 0) as scheme_units,
        coalesce(sum(p.units) filter (where p.invoice_date between e.end_date + 1 and e.end_date + 30), 0) as post_30d_units,
        e.end_date + 60 <= run.as_of_date as is_follow_through_complete,
        e.end_date <= run.as_of_date as is_window_complete
    from eligible as e
    cross join run
    left join primary_daily as p
        on p.distributor_id = e.distributor_id
        and p.category = e.category
        and p.invoice_date between e.start_date - 90 and greatest(e.quarter_end, e.end_date + 30)
    where e.start_date <= run.as_of_date
    group by e.distributor_id, e.region, e.tier, e.category, e.fiscal_quarter_label, e.start_date, e.end_date,
        e.quarter_start, e.quarter_end, run.as_of_date
),

shares as (
    select
        *,
        (window_units::numeric / window_days_observed) / nullif(baseline_units::numeric / 90, 0) as rate_ratio,
        window_units::numeric / nullif(quarter_units, 0) as window_share,
        (post_30d_units::numeric / 30) / nullif(baseline_units::numeric / 90, 0) as post_rate_ratio
    from volumes
),

baseline_shares as (
    select
        a.distributor_id,
        a.category,
        a.start_date,
        greatest(
            percentile_cont(0.5) within group (order by b.window_share),
            15.0 / 91
        ) as baseline_share
    from shares as a
    inner join shares as b
        on b.distributor_id = a.distributor_id
        and b.category = a.category
        and b.start_date <> a.start_date
        and b.is_window_complete
    group by a.distributor_id, a.category, a.start_date
),

category_dos as (   -- channel days of stock per distributor x category x day
    select
        inv.distributor_id,
        p.category,
        inv.date_day,
        sum(inv.stock_units) / nullif(sum(inv.avg_daily_secondary_units), 0) as days_of_stock
    from {{ ref('fct_channel_inventory_daily') }} as inv
    inner join {{ ref('stg_products') }} as p on p.sku = inv.sku
    where p.category in (select distinct category from windows) and inv.avg_daily_secondary_units is not null
    group by inv.distributor_id, p.category, inv.date_day
),

follow_through as (
    select
        s.distributor_id,
        s.category,
        s.start_date,
        percentile_cont(0.5) within group (order by cd.days_of_stock)
            filter (where cd.date_day between s.start_date - 90 and s.start_date - 1) as dos_pre_window_median,
        avg(cd.days_of_stock) filter (where cd.date_day between s.end_date + 1 and s.end_date + 60) as dos_post_60d_mean
    from shares as s
    inner join category_dos as cd
        on cd.distributor_id = s.distributor_id
        and cd.category = s.category
        and cd.date_day between s.start_date - 90 and s.end_date + 60
    group by s.distributor_id, s.category, s.start_date
)

select
    s.distributor_id,
    s.region,
    s.tier,
    s.category,
    s.fiscal_quarter_label,
    s.start_date as window_start_date,
    s.end_date as window_end_date,
    s.is_window_complete,
    s.window_days_observed,
    s.window_units,
    s.baseline_units,
    s.quarter_units,
    s.scheme_invoices,
    s.scheme_units,
    round(s.rate_ratio, 3) as rate_ratio,
    round(s.window_share, 4) as window_share,
    round(b.baseline_share::numeric, 4) as baseline_share,
    round(s.window_share / nullif(b.baseline_share::numeric, 0), 3) as concentration_ratio,
    coalesce(s.rate_ratio >= 2.0, false) as is_stuffing_flag,   -- detectors.yaml stuffing.flag (v1)
    coalesce(s.rate_ratio >= 2.0 and s.scheme_invoices >= 1, false) as is_stuffing_flag_v2,   -- stuffing_v2.flag
    s.is_follow_through_complete,
    round(s.post_rate_ratio, 3) as post_rate_ratio,
    coalesce(
        s.rate_ratio >= 2.0 and s.scheme_invoices >= 1 and s.is_follow_through_complete
        and (s.post_rate_ratio < 1.0 or f.dos_post_60d_mean - f.dos_pre_window_median >= 3),
        false
    ) as is_stuffing_confirmed_v2,   -- stuffing_v2.confirmed
    round(f.dos_pre_window_median::numeric, 1) as dos_pre_window_median,
    round(f.dos_post_60d_mean::numeric, 1) as dos_post_60d_mean,
    round((f.dos_post_60d_mean - f.dos_pre_window_median)::numeric, 1) as dos_excess_60d
from shares as s
left join baseline_shares as b
    on b.distributor_id = s.distributor_id and b.category = s.category and b.start_date = s.start_date
left join follow_through as f
    on f.distributor_id = s.distributor_id and f.category = s.category and f.start_date = s.start_date
