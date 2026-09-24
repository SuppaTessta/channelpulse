select c.collection_id, c.payment_date, i.invoice_date
from {{ ref('stg_collections') }} as c
inner join {{ ref('stg_primary_invoices') }} as i on i.invoice_id = c.invoice_id
where c.payment_date < i.invoice_date
