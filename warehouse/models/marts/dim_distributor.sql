{{ config(post_hook="{{ apply_region_rls() }}") }}

with invoices as (
    select distributor_id, min(invoice_date) as first_invoice_date, max(invoice_date) as last_invoice_date
    from {{ ref('stg_primary_invoices') }}
    group by distributor_id
),

retailers as (
    select distributor_id, count(*) as retailer_count
    from {{ ref('stg_retailers') }}
    group by distributor_id
)

select
    d.distributor_id,
    d.distributor_name,
    d.tier,
    d.state,
    d.district,
    d.pincode,
    g.region,                                   -- D4: region of the distributor's pincode
    d.onboarding_date,
    d.credit_limit_inr,
    d.rep_id,
    r.rep_name,
    d.distributor_status,
    i.first_invoice_date,
    i.last_invoice_date,
    coalesce(rt.retailer_count, 0) as retailer_count
from {{ ref('stg_distributors') }} as d
left join {{ ref('stg_geo_pincodes') }} as g on g.pincode = d.pincode
left join {{ ref('stg_sales_reps') }} as r on r.rep_id = d.rep_id
left join invoices as i on i.distributor_id = d.distributor_id
left join retailers as rt on rt.distributor_id = d.distributor_id
