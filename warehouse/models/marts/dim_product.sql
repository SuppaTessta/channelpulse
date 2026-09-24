with made_at as (
    select sku, string_agg(distinct plant_id, ',' order by plant_id) as producing_plants
    from {{ ref('stg_production_batches') }}
    group by sku
)

select
    p.sku,
    p.product_name,
    p.category,
    p.capacity_l,
    p.list_price_inr,
    p.warranty_months,
    p.launched_date,
    p.category = 'tank' as is_serialised,          -- D3
    coalesce(m.producing_plants, 'traded') as producing_plants  -- D6: sanitaryware is bought in
from {{ ref('stg_products') }} as p
left join made_at as m on m.sku = p.sku
