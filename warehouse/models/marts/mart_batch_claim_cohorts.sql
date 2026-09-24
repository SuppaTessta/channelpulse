-- Batch Cohort Heatmap ("Nevada chart", PLAN §9.3): one row per batch x month since shipment.
-- The in-service clock starts at shipment rather than install because ~30% of units never register an install
-- date (decisions D8). claims_per_1000_units = claims / (units_shipped / 1000) for the cohort (PLAN §7).
-- Legacy batches (made before month 1) have no shipment history, so they are not cohorts here.
{{ config(indexes=[{'columns': ['batch_id']}, {'columns': ['mfg_month', 'plant_id']}]) }}

with run as (
    select as_of_date from {{ ref('stg_generation_run') }}
),

cohorts as (
    select batch_id, units_shipped, first_ship_date, last_ship_date
    from {{ ref('dim_batch') }}
    where not is_legacy and units_shipped > 0
),

ages as (
    select c.batch_id, c.units_shipped, c.last_ship_date, age.months_since_ship
    from cohorts as c
    cross join run
    cross join lateral generate_series(
        0, floor((run.as_of_date - c.first_ship_date) / {{ var('days_per_month') }})::int
    ) as age (months_since_ship)
),

claims as (
    select
        batch_id,
        months_since_ship,
        count(*) as claims,
        count(*) filter (where failure_mode = 'base_crack') as claims_base_crack,
        count(*) filter (where failure_mode = 'leak') as claims_leak,
        count(*) filter (where failure_mode = 'fitting_failure') as claims_fitting_failure,
        count(*) filter (where failure_mode = 'discoloration') as claims_discoloration,
        count(*) filter (where failure_mode = 'other') as claims_other
    from {{ ref('fct_warranty_claims') }}
    where not is_legacy and ship_date is not null
    group by batch_id, months_since_ship
)

select
    a.batch_id,
    b.plant_id,
    b.line_no,
    b.sku,
    b.capacity_l,
    b.mfg_date,
    b.mfg_month,
    b.resin_lot_id,
    a.months_since_ship,
    a.units_shipped,
    coalesce(cl.claims, 0) as claims,
    coalesce(cl.claims_base_crack, 0) as claims_base_crack,
    coalesce(cl.claims_leak, 0) as claims_leak,
    coalesce(cl.claims_fitting_failure, 0) as claims_fitting_failure,
    coalesce(cl.claims_discoloration, 0) as claims_discoloration,
    coalesce(cl.claims_other, 0) as claims_other,
    sum(coalesce(cl.claims, 0)) over cohort as cumulative_claims,
    sum(coalesce(cl.claims_base_crack, 0)) over cohort as cumulative_base_crack_claims,
    round(sum(coalesce(cl.claims, 0)) over cohort * 1000.0 / a.units_shipped, 2) as cumulative_claims_per_1000,
    -- every unit in the batch has been out at least this many whole months
    (run.as_of_date - a.last_ship_date) >= (a.months_since_ship + 1) * {{ var('days_per_month') }} as is_fully_observed
from ages as a
inner join {{ ref('dim_batch') }} as b on b.batch_id = a.batch_id
left join claims as cl on cl.batch_id = a.batch_id and cl.months_since_ship = a.months_since_ship
cross join run
window cohort as (partition by a.batch_id order by a.months_since_ship)
