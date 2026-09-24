-- Secondary sales can't exceed opening stock + primary receipts (build prompt): implied stock never goes negative.
select distributor_id, sku, date_day, stock_units
from {{ ref('fct_channel_inventory_daily') }}
where stock_units < 0
