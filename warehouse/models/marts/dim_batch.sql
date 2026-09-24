with run as (
    select as_of_date from {{ ref('stg_generation_run') }}
),

units as (
    select
        s.batch_id,
        count(*) as units_serialised,
        count(*) filter (where s.is_shipped) as units_shipped,
        -- warranty_registration_rate denominators: only shipments old enough to have had 90 days to register
        count(*) filter (where s.ship_date <= run.as_of_date - 90) as units_shipped_90d_matured,
        count(*) filter (where s.ship_date <= run.as_of_date - 90 and s.is_registered_within_90d) as units_registered_within_90d,
        min(s.ship_date) as first_ship_date,
        max(s.ship_date) as last_ship_date
    from {{ ref('int_serials') }} as s
    cross join run
    group by s.batch_id
),

claims as (
    select s.batch_id, count(*) as claims
    from {{ ref('stg_warranty_claims') }} as c
    inner join {{ ref('int_serials') }} as s on s.serial = c.serial
    group by s.batch_id
)

select
    b.batch_id,
    b.plant_id,
    pl.plant_name,
    b.line_no,
    b.shift,
    b.sku,
    p.category,
    p.capacity_l,
    b.mfg_date,
    date_trunc('month', b.mfg_date)::date as mfg_month,
    b.resin_lot_id,
    b.qty_produced,
    b.qc_pass_rate,
    b.mfg_date < '{{ var("window_start") }}'::date as is_legacy,
    coalesce(u.units_serialised, 0) as units_serialised,
    coalesce(u.units_shipped, 0) as units_shipped,
    coalesce(u.units_shipped_90d_matured, 0) as units_shipped_90d_matured,
    coalesce(u.units_registered_within_90d, 0) as units_registered_within_90d,
    u.first_ship_date,
    u.last_ship_date,
    coalesce(c.claims, 0) as claims
from {{ ref('stg_production_batches') }} as b
inner join {{ ref('stg_plants') }} as pl on pl.plant_id = b.plant_id
inner join {{ ref('stg_products') }} as p on p.sku = b.sku
left join units as u on u.batch_id = b.batch_id
left join claims as c on c.batch_id = b.batch_id
