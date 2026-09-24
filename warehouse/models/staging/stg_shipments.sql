select
    shipment_id,
    serial,
    distributor_id,
    ship_date
from {{ source('raw', 'shipments') }}
