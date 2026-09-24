-- Reports never precede the sale and arrive within the 35-day cap (decisions D12).
select record_id, sale_date, reported_date
from {{ ref('stg_secondary_sales') }}
where reported_date < sale_date or reported_date - sale_date > 35
