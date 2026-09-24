select
    as_of_date,
    anchor_date,
    seed,
    generated_at
from {{ source('raw', 'generation_run') }}
