select
    invoice_id,
    distributor_id,
    invoice_date,
    scheme_id,
    total_amount_inr::numeric(14, 2) as total_amount_inr,
    due_date
from {{ source('raw', 'primary_invoices') }}
