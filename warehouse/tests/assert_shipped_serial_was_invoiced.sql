-- Every shipped serial's batch was invoiced to the receiving distributor (one batch per line, PLAN §2).
select s.serial, s.distributor_id, s.batch_id
from {{ ref('int_serials') }} as s
where s.is_shipped
    and not exists (
        select 1
        from {{ ref('stg_primary_invoice_lines') }} as l
        inner join {{ ref('stg_primary_invoices') }} as i on i.invoice_id = l.invoice_id
        where l.batch_id = s.batch_id and i.distributor_id = s.distributor_id
    )
