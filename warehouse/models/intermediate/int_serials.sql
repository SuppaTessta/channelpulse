-- One row per serialised tank: where it was made, when and to whom it shipped, and its registration.
{{ config(materialized='table') }}

with serial_shipments as (
    select serial, distributor_id, ship_date
    from {{ ref('stg_shipments') }}
    where serial is not null
)

select
    su.serial,
    su.sku,
    su.batch_id,
    b.plant_id,
    b.line_no,
    b.resin_lot_id,
    su.mfg_date,
    date_trunc('month', su.mfg_date)::date as mfg_month,
    su.mfg_date < '{{ var("window_start") }}'::date as is_legacy,  -- D7: made before month 1, no shipment history
    sh.serial is not null as is_shipped,
    sh.ship_date,
    sh.distributor_id,
    i.install_date,
    i.install_date is not null as is_registered,
    coalesce(i.install_date - sh.ship_date <= 90, false) as is_registered_within_90d,
    i.registered_via,
    i.installer_id,
    i.install_pincode,
    g.district as install_district,
    g.state as install_state,
    g.region as install_region
from {{ ref('stg_serial_units') }} as su
inner join {{ ref('stg_production_batches') }} as b on b.batch_id = su.batch_id
left join serial_shipments as sh on sh.serial = su.serial
left join {{ ref('stg_installations') }} as i on i.serial = su.serial
left join {{ ref('stg_geo_pincodes') }} as g on g.pincode = i.install_pincode
