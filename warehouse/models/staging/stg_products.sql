select
    sku,
    name as product_name,
    category,
    capacity_l,
    list_price_inr::numeric(12, 2) as list_price_inr,
    warranty_months,
    launched_date
from {{ source('raw', 'products') }}
