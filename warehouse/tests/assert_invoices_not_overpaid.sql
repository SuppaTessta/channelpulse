select invoice_id, invoice_amount_inr, paid_amount_inr
from {{ ref('fct_invoice_collections') }}
where paid_amount_inr > invoice_amount_inr + 0.5
