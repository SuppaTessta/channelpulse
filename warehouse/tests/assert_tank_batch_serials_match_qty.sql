-- Every QC-passed tank is serialised: one serial_units row per unit produced (decisions D3).
select batch_id, qty_produced, units_serialised
from {{ ref('dim_batch') }}
where category = 'tank' and units_serialised <> qty_produced
