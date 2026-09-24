select
    scheme_id,
    name as scheme_name,
    start_date,
    end_date,
    discount_pct::numeric(5, 4) as discount_pct,
    min_slab_units,
    applies_to_category
from {{ source('raw', 'schemes') }}
