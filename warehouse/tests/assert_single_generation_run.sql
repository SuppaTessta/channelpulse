select count(*) as runs
from {{ ref('stg_generation_run') }}
having count(*) <> 1
