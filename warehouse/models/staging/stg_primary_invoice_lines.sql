select
    line_id,
    invoice_id,
    sku,
    qty,
    unit_price_inr::numeric(12, 2) as unit_price_inr,
    batch_id
from {{ source('raw', 'primary_invoice_lines') }}
