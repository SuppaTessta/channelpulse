-- One row per warranty claim (all claims are on serialised tanks, decisions D3), with the unit's full lineage.
select
    c.claim_id,
    c.claim_date,
    date_trunc('month', c.claim_date)::date as claim_month,
    c.failure_mode,
    c.cost_inr,
    c.claim_status,
    c.technician_notes,
    c.serial,
    s.sku,
    p.category,
    p.capacity_l,
    s.batch_id,
    s.plant_id,
    s.line_no,
    s.resin_lot_id,
    s.mfg_date,
    s.mfg_month,
    s.is_legacy,
    s.ship_date,
    s.distributor_id,
    d.region as distributor_region,
    s.install_date,
    s.installer_id,                       -- from installations (D1)
    c.installer_id as claim_installer_id, -- technician-recorded copy
    s.install_district,
    s.install_state,
    s.install_region,
    c.claim_date - s.ship_date as days_since_ship,
    c.claim_date - s.install_date as days_since_install,
    floor((c.claim_date - s.ship_date) / {{ var('days_per_month') }})::int as months_since_ship
from {{ ref('stg_warranty_claims') }} as c
inner join {{ ref('int_serials') }} as s on s.serial = c.serial
inner join {{ ref('stg_products') }} as p on p.sku = s.sku
left join {{ ref('dim_distributor') }} as d on d.distributor_id = s.distributor_id
