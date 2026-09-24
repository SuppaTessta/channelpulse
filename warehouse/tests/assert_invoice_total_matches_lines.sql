select i.invoice_id, i.total_amount_inr, sum(l.qty * l.unit_price_inr) as lines_total
from {{ ref('stg_primary_invoices') }} as i
inner join {{ ref('stg_primary_invoice_lines') }} as l on l.invoice_id = i.invoice_id
group by i.invoice_id, i.total_amount_inr
having abs(i.total_amount_inr - sum(l.qty * l.unit_price_inr)) > 0.05
