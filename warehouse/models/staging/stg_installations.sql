select
    serial,
    pincode as install_pincode,
    install_date,
    registered_via,
    installer_id,
    _loaded_at as last_updated_date
from {{ source('raw', 'installations') }}
