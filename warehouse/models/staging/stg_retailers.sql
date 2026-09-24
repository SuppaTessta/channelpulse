select
    retailer_id,
    distributor_id,
    name as retailer_name,
    pincode,
    onboarding_date
from {{ source('raw', 'retailers') }}
