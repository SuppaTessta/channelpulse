select
    serial,
    batch_id,
    sku,
    mfg_date
from {{ source('raw', 'serial_units') }}
