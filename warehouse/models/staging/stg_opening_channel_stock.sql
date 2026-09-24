select
    distributor_id,
    sku,
    qty as opening_qty,
    as_of_date as opening_date
from {{ source('raw', 'opening_channel_stock') }}
