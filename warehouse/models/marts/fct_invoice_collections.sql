-- One row per primary invoice with its payment status as of the as-of date (decisions D13).
-- dso = sum(invoice_amount_inr * days_outstanding) / sum(invoice_amount_inr): open invoices age to the as-of
-- date, so a distributor who stops paying shows up at once instead of only when late payments finally land.
-- collections_efficiency = sum(paid_within_terms_inr) / sum(invoice_amount_inr) over invoices already due.
{{ config(
    post_hook="{{ apply_region_rls() }}",
    indexes=[{'columns': ['distributor_id', 'invoice_date']}]
) }}

with run as (
    select as_of_date from {{ ref('stg_generation_run') }}
),

payments as (
    select
        c.invoice_id,
        c.payment_date,
        c.amount_inr,
        sum(c.amount_inr) over (partition by c.invoice_id order by c.payment_date, c.collection_id) as paid_to_date
    from {{ ref('stg_collections') }} as c
),

per_invoice as (
    select
        i.invoice_id,
        i.distributor_id,
        i.invoice_date,
        i.due_date,
        i.scheme_id,
        i.total_amount_inr as invoice_amount_inr,
        coalesce(sum(p.amount_inr), 0) as paid_amount_inr,
        coalesce(sum(p.amount_inr) filter (where p.payment_date <= i.due_date), 0) as paid_within_terms_inr,
        max(p.payment_date) as last_payment_date,
        min(p.payment_date) filter (where p.paid_to_date >= i.total_amount_inr - 0.5) as fully_paid_date
    from {{ ref('stg_primary_invoices') }} as i
    left join payments as p on p.invoice_id = i.invoice_id
    group by i.invoice_id, i.distributor_id, i.invoice_date, i.due_date, i.scheme_id, i.total_amount_inr
)

select
    pi.invoice_id,
    pi.distributor_id,
    d.region,
    d.state,
    d.tier,
    pi.invoice_date,
    pi.due_date,
    pi.scheme_id,
    pi.invoice_amount_inr,
    pi.paid_amount_inr,
    pi.paid_within_terms_inr,
    pi.invoice_amount_inr - pi.paid_amount_inr as open_amount_inr,
    pi.last_payment_date,
    pi.fully_paid_date,
    pi.fully_paid_date is null as is_open,
    coalesce(pi.fully_paid_date, run.as_of_date) - pi.invoice_date as days_outstanding,
    greatest(coalesce(pi.fully_paid_date, run.as_of_date) - pi.due_date, 0) as days_past_due,
    pi.due_date <= run.as_of_date as is_due
from per_invoice as pi
inner join {{ ref('dim_distributor') }} as d on d.distributor_id = pi.distributor_id
cross join run
