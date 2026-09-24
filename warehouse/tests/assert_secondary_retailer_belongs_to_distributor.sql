select s.record_id, s.distributor_id, r.distributor_id as retailer_distributor_id
from {{ ref('stg_secondary_sales') }} as s
inner join {{ ref('stg_retailers') }} as r on r.retailer_id = s.retailer_id
where r.distributor_id <> s.distributor_id
