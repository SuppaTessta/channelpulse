-- A scheme-tagged invoice clears its scheme's slab on the scheme's category lines (decisions D9).
select
    i.invoice_id,
    s.scheme_id,
    s.min_slab_units,
    coalesce(sum(l.qty) filter (where p.category = s.applies_to_category), 0) as category_units
from {{ ref('stg_primary_invoices') }} as i
inner join {{ ref('stg_schemes') }} as s on s.scheme_id = i.scheme_id
inner join {{ ref('stg_primary_invoice_lines') }} as l on l.invoice_id = i.invoice_id
inner join {{ ref('stg_products') }} as p on p.sku = l.sku
group by i.invoice_id, s.scheme_id, s.min_slab_units
having coalesce(sum(l.qty) filter (where p.category = s.applies_to_category), 0) < s.min_slab_units
