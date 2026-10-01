-- distributor_health_score (PLAN §7), one row per distributor x completed ISO week, implemented exactly as
-- pre-registered in detectors/detectors.yaml (distributor_health). Everything is point-in-time: the row for the
-- week ending S only uses what was visible at S. Secondary sales are read up to S - 17 days (decisions D12),
-- and rows sold by then but reported after S are held back. Payments are counted only if made by S.
{{ config(
    post_hook="{{ apply_region_rls() }}",
    indexes=[{'columns': ['distributor_id', 'week_start']}, {'columns': ['week_start']}]
) }}
{% set h = var('secondary_horizon_days') %}

with weeks as (
    select distinct week_start, week_end as snapshot_date
    from {{ ref('int_calendar') }}
    where is_complete_week
),

distributor_weeks as (
    select
        d.distributor_id,
        d.region,
        d.first_invoice_date,
        w.week_start,
        w.snapshot_date,
        w.snapshot_date - {{ h }} as anchor_date
    from {{ ref('dim_distributor') }} as d
    cross join weeks as w
    where d.first_invoice_date is not null and w.snapshot_date >= d.first_invoice_date
),

unreported as (   -- sold by the anchor date but not yet reported at the snapshot (reporting lag cap is 35 days)
    select dw.distributor_id, dw.snapshot_date, sum(s.qty) as units
    from distributor_weeks as dw
    inner join {{ ref('stg_secondary_sales') }} as s
        on s.distributor_id = dw.distributor_id
        and s.sale_date > dw.anchor_date - 35
        and s.sale_date <= dw.anchor_date
        and s.reported_date > dw.snapshot_date
    group by dw.distributor_id, dw.snapshot_date
),

dso as (
    select
        dw.distributor_id,
        dw.snapshot_date,
        sum(ic.invoice_amount_inr * (least(coalesce(ic.fully_paid_date, dw.snapshot_date), dw.snapshot_date) - ic.invoice_date))
            / nullif(sum(ic.invoice_amount_inr), 0) as dso_days
    from distributor_weeks as dw
    inner join {{ ref('fct_invoice_collections') }} as ic
        on ic.distributor_id = dw.distributor_id
        and ic.invoice_date > dw.snapshot_date - 84
        and ic.invoice_date <= dw.snapshot_date
    group by dw.distributor_id, dw.snapshot_date
),

measures as (
    select
        dw.distributor_id,
        dw.region,
        dw.first_invoice_date,
        dw.week_start,
        dw.snapshot_date,
        now_.cum_secondary_units - coalesce(u.units, 0) - coalesce(m56.cum_secondary_units, 0) as secondary_units_8w,
        coalesce(ly.cum_secondary_units, 0) - coalesce(ly56.cum_secondary_units, 0) as secondary_units_8w_last_year,
        now_.cum_primary_units - coalesce(m84.cum_primary_units, 0) as primary_units_12w,
        now_.cum_secondary_units - coalesce(u.units, 0) - coalesce(m84.cum_secondary_units, 0) as secondary_units_12w,
        now_.stock_units + coalesce(u.units, 0) as stock_units,
        now_.cum_secondary_units - coalesce(u.units, 0) - coalesce(m30.cum_secondary_units, 0) as secondary_units_30d,
        dso.dso_days,
        dw.snapshot_date - coalesce(vis.last_verified_visit_date, dw.first_invoice_date) as days_since_verified_visit
    from distributor_weeks as dw
    inner join {{ ref('int_distributor_daily') }} as now_
        on now_.distributor_id = dw.distributor_id and now_.date_day = dw.anchor_date
    inner join {{ ref('int_distributor_daily') }} as vis
        on vis.distributor_id = dw.distributor_id and vis.date_day = dw.snapshot_date
    left join {{ ref('int_distributor_daily') }} as m30
        on m30.distributor_id = dw.distributor_id and m30.date_day = dw.anchor_date - 30
    left join {{ ref('int_distributor_daily') }} as m56
        on m56.distributor_id = dw.distributor_id and m56.date_day = dw.anchor_date - 56
    left join {{ ref('int_distributor_daily') }} as m84
        on m84.distributor_id = dw.distributor_id and m84.date_day = dw.anchor_date - 84
    left join {{ ref('int_distributor_daily') }} as ly
        on ly.distributor_id = dw.distributor_id and ly.date_day = dw.anchor_date - 364
    left join {{ ref('int_distributor_daily') }} as ly56
        on ly56.distributor_id = dw.distributor_id and ly56.date_day = dw.anchor_date - 364 - 56
    left join unreported as u on u.distributor_id = dw.distributor_id and u.snapshot_date = dw.snapshot_date
    left join dso on dso.distributor_id = dw.distributor_id and dso.snapshot_date = dw.snapshot_date
),

ratios as (
    select
        *,
        secondary_units_8w::numeric / nullif(secondary_units_8w_last_year, 0) as secondary_trend_ratio,
        primary_units_12w::numeric / nullif(secondary_units_12w, 0) as primary_secondary_ratio,
        stock_units / nullif(secondary_units_30d / 30.0, 0) as days_of_stock
    from measures
),

own_medians as (   -- each distributor's own trailing-52-week medians (the current week excluded)
    select
        a.distributor_id,
        a.snapshot_date,
        percentile_cont(0.5) within group (order by b.days_of_stock) as days_of_stock_median_52w,
        percentile_cont(0.5) within group (order by b.dso_days) as dso_median_52w
    from ratios as a
    inner join ratios as b
        on b.distributor_id = a.distributor_id
        and b.snapshot_date < a.snapshot_date
        and b.snapshot_date >= a.snapshot_date - 364
    group by a.distributor_id, a.snapshot_date
),

components as (
    select
        r.*,
        r.days_of_stock / nullif(m.days_of_stock_median_52w, 0) as days_of_stock_vs_median,
        r.dso_days / nullif(m.dso_median_52w, 0) as dso_vs_median,
        r.snapshot_date >= r.first_invoice_date + 364   -- detectors.yaml min_history_weeks: 52
            -- last year's 8-week window must lie wholly inside the data, or the trend ratio is inflated
            and r.snapshot_date - {{ h }} - 364 - 56 >= '{{ var("window_start") }}'::date
            and r.secondary_trend_ratio is not null
            and r.primary_secondary_ratio is not null
            and r.days_of_stock is not null
            and m.days_of_stock_median_52w is not null
            and r.dso_days is not null
            and m.dso_median_52w is not null as is_scored
    from ratios as r
    left join own_medians as m on m.distributor_id = r.distributor_id and m.snapshot_date = r.snapshot_date
),

ranked as (   -- percentile among region peers that week; 0 = worst in region, 1 = best
    select
        *,
        percent_rank() over (partition by region, snapshot_date order by secondary_trend_ratio) as pct_secondary_trend,
        percent_rank() over (partition by region, snapshot_date order by primary_secondary_ratio desc) as pct_primary_secondary_gap,
        percent_rank() over (partition by region, snapshot_date order by days_of_stock_vs_median desc) as pct_days_of_stock_dev,
        percent_rank() over (partition by region, snapshot_date order by dso_vs_median desc) as pct_dso_trend,
        percent_rank() over (partition by region, snapshot_date order by days_since_verified_visit desc) as pct_visit_recency
    from components
    where is_scored
),

scored as (
    select
        *,
        round((100 * (0.35 * pct_secondary_trend + 0.20 * pct_primary_secondary_gap + 0.15 * pct_days_of_stock_dev
                      + 0.20 * pct_dso_trend + 0.10 * pct_visit_recency))::numeric, 1) as health_score
    from ranked
),

flagged as (
    select
        *,
        -- Detector v2 in production (decisions D46-D48): the secondary gate is absolute, not a regional
        -- percentile. Sell-out under 0.8x the same 8 weeks a year earlier while sell-in runs above 1.1x sell-out.
        health_score < 30 and secondary_trend_ratio < 0.8 and primary_secondary_ratio > 1.1 as is_flag_week,
        health_score < 30 and pct_secondary_trend * 100 < 15 as is_flag_week_v1   -- the pre-registered v1 rule
    from scored
)

select
    c.distributor_id,
    c.region,
    c.week_start,
    c.snapshot_date,
    c.secondary_units_8w,
    c.secondary_units_8w_last_year,
    round(c.secondary_trend_ratio, 3) as secondary_trend_ratio,
    c.primary_units_12w,
    c.secondary_units_12w,
    round(c.primary_secondary_ratio, 3) as primary_secondary_ratio,
    round(c.days_of_stock::numeric, 1) as days_of_stock,
    round(c.days_of_stock_vs_median::numeric, 3) as days_of_stock_vs_median,
    round(c.dso_days, 1) as dso_days,
    round(c.dso_vs_median::numeric, 3) as dso_vs_median,
    c.days_since_verified_visit,
    c.is_scored,
    round((100 * f.pct_secondary_trend)::numeric, 1) as score_secondary_trend,
    round((100 * f.pct_primary_secondary_gap)::numeric, 1) as score_primary_secondary_gap,
    round((100 * f.pct_days_of_stock_dev)::numeric, 1) as score_days_of_stock_dev,
    round((100 * f.pct_dso_trend)::numeric, 1) as score_dso_trend,
    round((100 * f.pct_visit_recency)::numeric, 1) as score_visit_recency,
    f.health_score,
    coalesce(f.is_flag_week, false) as is_flag_week,
    coalesce(
        f.is_flag_week
        and lag(f.is_flag_week, 1) over (partition by c.distributor_id order by c.snapshot_date)
        and lag(f.is_flag_week, 2) over (partition by c.distributor_id order by c.snapshot_date),
        false
    ) as is_at_risk,
    coalesce(f.is_flag_week_v1, false) as is_flag_week_v1,
    coalesce(
        f.is_flag_week_v1
        and lag(f.is_flag_week_v1, 1) over (partition by c.distributor_id order by c.snapshot_date)
        and lag(f.is_flag_week_v1, 2) over (partition by c.distributor_id order by c.snapshot_date),
        false
    ) as is_at_risk_v1
from components as c
left join flagged as f on f.distributor_id = c.distributor_id and f.snapshot_date = c.snapshot_date
