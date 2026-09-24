select
    collection_id,
    invoice_id,
    payment_date,
    amount_inr::numeric(14, 2) as amount_inr
from {{ source('raw', 'collections') }}
