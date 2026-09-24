select l.line_id, l.sku, b.sku as batch_sku
from {{ ref('stg_primary_invoice_lines') }} as l
inner join {{ ref('stg_production_batches') }} as b on b.batch_id = l.batch_id
where b.sku <> l.sku
