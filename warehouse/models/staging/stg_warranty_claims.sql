select
    claim_id,
    serial,
    claim_date,
    failure_mode,
    cost_inr::numeric(12, 2) as cost_inr,
    status as claim_status,
    technician_notes,
    installer_id
from {{ source('raw', 'warranty_claims') }}
