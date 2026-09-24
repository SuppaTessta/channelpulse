-- Light dedup: distributors occasionally re-send an upload. A re-sent record repeats
-- (distributor, retailer, sku, sale_date, qty) under a new record_id and a later reported_date;
-- keep the earliest-reported copy.
with ranked as (
    select
        *,
        row_number() over (
            partition by distributor_id, coalesce(retailer_id, ''), sku, sale_date, qty
            order by reported_date, record_id
        ) as copy_rank
    from {{ source('raw', 'secondary_sales') }}
)

select
    record_id,
    distributor_id,
    retailer_id,
    sku,
    sale_date,
    qty,
    reported_date,
    source as report_source
from ranked
where copy_rank = 1
