select su.serial, p.category
from {{ ref('stg_serial_units') }} as su
inner join {{ ref('stg_products') }} as p on p.sku = su.sku
where p.category <> 'tank'
