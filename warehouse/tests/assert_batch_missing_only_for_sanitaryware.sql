-- Traded sanitaryware has no production batch; everything else ships from one (decisions D6).
select l.line_id, l.sku, p.category, l.batch_id
from {{ ref('stg_primary_invoice_lines') }} as l
inner join {{ ref('stg_products') }} as p on p.sku = l.sku
where (l.batch_id is null) <> (p.category = 'sanitaryware')
