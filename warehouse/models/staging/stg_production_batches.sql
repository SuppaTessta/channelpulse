select
    batch_id,
    plant_id,
    sku,
    line_no::integer as line_no,
    shift,
    mfg_date,
    resin_lot_id,
    qty_produced,
    qc_pass_rate::numeric(5, 4) as qc_pass_rate
from {{ source('raw', 'production_batches') }}
