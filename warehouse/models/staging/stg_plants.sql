select
    plant_id,
    name as plant_name,
    city,
    state,
    plant_type
from {{ source('raw', 'plants') }}
