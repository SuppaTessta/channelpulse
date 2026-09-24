select
    distributor_id,
    name as distributor_name,
    tier,
    state,
    district,
    pincode,
    onboarding_date,
    credit_limit_inr::numeric(14, 2) as credit_limit_inr,
    sales_rep_id as rep_id,
    status as distributor_status
from {{ source('raw', 'distributors') }}
