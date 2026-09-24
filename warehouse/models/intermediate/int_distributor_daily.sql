-- Dense distributor x day series (all SKUs, units) with running totals, so any trailing window is a
-- difference of two cumulative values. Feeds the point-in-time weekly health score.
{{ config(
    materialized='table',
    indexes=[{'columns': ['distributor_id', 'date_day'], 'unique': True}]
) }}

with primary_daily as (
    select i.distributor_id, i.invoice_date as flow_date, sum(l.qty) as units
    from {{ ref('stg_primary_invoice_lines') }} as l
    inner join {{ ref('stg_primary_invoices') }} as i on i.invoice_id = l.invoice_id
    group by i.distributor_id, i.invoice_date
),

secondary_daily as (
    select distributor_id, sale_date as flow_date, sum(qty) as units
    from {{ ref('stg_secondary_sales') }}
    group by distributor_id, sale_date
),

verified_visits as (
    select distinct distributor_id, visit_date
    from {{ ref('stg_field_visits') }}
    where is_geofence_verified
),

opening as (
    select distributor_id, sum(opening_qty) as units
    from {{ ref('stg_opening_channel_stock') }}
    group by distributor_id
)

select
    d.distributor_id,
    c.date_day,
    coalesce(p.units, 0) as primary_units,
    coalesce(s.units, 0) as secondary_units,
    sum(coalesce(p.units, 0)) over w as cum_primary_units,
    sum(coalesce(s.units, 0)) over w as cum_secondary_units,
    coalesce(o.units, 0) + sum(coalesce(p.units, 0) - coalesce(s.units, 0)) over w as stock_units,
    max(v.visit_date) over w as last_verified_visit_date
from {{ ref('stg_distributors') }} as d
cross join {{ ref('int_calendar') }} as c
left join primary_daily as p on p.distributor_id = d.distributor_id and p.flow_date = c.date_day
left join secondary_daily as s on s.distributor_id = d.distributor_id and s.flow_date = c.date_day
left join verified_visits as v on v.distributor_id = d.distributor_id and v.visit_date = c.date_day
left join opening as o on o.distributor_id = d.distributor_id
window w as (partition by d.distributor_id order by c.date_day)
