-- The generator never emits a fact dated after the as-of date (decisions D14).
with run as (select as_of_date from {{ ref('stg_generation_run') }})

select 'invoice' as fact, invoice_id as id, invoice_date as fact_date
from {{ ref('stg_primary_invoices') }}, run where invoice_date > run.as_of_date
union all
select 'secondary', record_id::text, reported_date
from {{ ref('stg_secondary_sales') }}, run where reported_date > run.as_of_date
union all
select 'shipment', shipment_id::text, ship_date
from {{ ref('stg_shipments') }}, run where ship_date > run.as_of_date
union all
select 'claim', claim_id, claim_date
from {{ ref('stg_warranty_claims') }}, run where claim_date > run.as_of_date
union all
select 'payment', collection_id::text, payment_date
from {{ ref('stg_collections') }}, run where payment_date > run.as_of_date
union all
select 'install', serial, install_date
from {{ ref('stg_installations') }}, run where install_date > run.as_of_date
union all
select 'batch', batch_id, mfg_date
from {{ ref('stg_production_batches') }}, run where mfg_date > run.as_of_date
