select
    pincode,
    district,
    state,
    region
from {{ ref('stg_geo_pincodes') }}
