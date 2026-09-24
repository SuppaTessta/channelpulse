select i.invoice_id, i.invoice_date, s.start_date, s.end_date
from {{ ref('stg_primary_invoices') }} as i
inner join {{ ref('stg_schemes') }} as s on s.scheme_id = i.scheme_id
where i.invoice_date not between s.start_date and s.end_date
