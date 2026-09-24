select invoice_id, invoice_date, due_date
from {{ ref('stg_primary_invoices') }}
where due_date <= invoice_date
