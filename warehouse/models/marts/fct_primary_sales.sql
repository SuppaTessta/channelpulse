-- Company -> distributor sell-in, one row per invoice line. primary_sales_value = sum(primary_value_inr).
{{ config(
    post_hook="{{ apply_region_rls() }}",
    indexes=[{'columns': ['distributor_id', 'invoice_date']}, {'columns': ['invoice_date']}]
) }}

select
    l.line_id,
    l.invoice_id,
    i.invoice_date,
    i.due_date,
    i.distributor_id,
    d.region,
    d.state,
    d.district,
    d.tier,
    l.sku,
    p.category,
    l.batch_id,
    b.plant_id,
    i.scheme_id,
    i.scheme_id is not null as is_scheme_invoice,
    l.qty,
    l.unit_price_inr,
    (l.qty * l.unit_price_inr)::numeric(14, 2) as primary_value_inr
from {{ ref('stg_primary_invoice_lines') }} as l
inner join {{ ref('stg_primary_invoices') }} as i on i.invoice_id = l.invoice_id
inner join {{ ref('dim_distributor') }} as d on d.distributor_id = i.distributor_id
inner join {{ ref('stg_products') }} as p on p.sku = l.sku
left join {{ ref('stg_production_batches') }} as b on b.batch_id = l.batch_id
