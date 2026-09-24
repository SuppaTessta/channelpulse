-- One row per day from month 1 through the as-of date, with Indian fiscal (Apr-Mar) and ISO keys.
{{ config(materialized='table') }}

with bounds as (
    select '{{ var("window_start") }}'::date as start_date, as_of_date
    from {{ ref('stg_generation_run') }}
),

days as (
    select generate_series(start_date, as_of_date, interval '1 day')::date as date_day, as_of_date
    from bounds
),

keyed as (
    select
        date_day,
        as_of_date,
        date_trunc('week', date_day)::date as week_start,
        date_trunc('month', date_day)::date as month_start,
        date_trunc('quarter', date_day)::date as fiscal_quarter_start,  -- Apr-Mar quarters align with calendar quarters
        extract(year from date_day)::int + (extract(month from date_day) >= 4)::int as fiscal_year,
        ((extract(month from date_day)::int + 8) % 12) / 3 + 1 as fiscal_quarter
    from days
)

select
    date_day,
    week_start,
    week_start + 6 as week_end,
    extract(isoyear from date_day)::int as iso_year,
    extract(week from date_day)::int as iso_week,
    month_start,
    (extract(year from date_day)::int * 12 + extract(month from date_day)::int)
        - (extract(year from '{{ var("window_start") }}'::date)::int * 12
           + extract(month from '{{ var("window_start") }}'::date)::int) + 1 as month_index,
    fiscal_year,
    'FY' || right(fiscal_year::text, 2) as fiscal_year_label,
    fiscal_quarter,
    'FY' || right(fiscal_year::text, 2) || 'Q' || fiscal_quarter as fiscal_quarter_label,
    fiscal_quarter_start,
    (fiscal_quarter_start + interval '3 months' - interval '1 day')::date as fiscal_quarter_end,
    (month_start + interval '1 month' - interval '1 day')::date <= as_of_date as is_complete_month,
    week_start + 6 <= as_of_date as is_complete_week
from keyed
