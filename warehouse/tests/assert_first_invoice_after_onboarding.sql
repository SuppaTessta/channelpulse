select distributor_id, onboarding_date, first_invoice_date
from {{ ref('dim_distributor') }}
where first_invoice_date < onboarding_date
