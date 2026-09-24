select
    pincode,
    district,
    state,
    region
from {{ source('raw', 'geo_pincodes') }}
