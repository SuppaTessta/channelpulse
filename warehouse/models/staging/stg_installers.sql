select
    installer_id,
    name as installer_name,
    district,
    certified as is_certified
from {{ source('raw', 'installers') }}
