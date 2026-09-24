select
    rep_id,
    name as rep_name,
    region,
    hire_date
from {{ source('raw', 'sales_reps') }}
