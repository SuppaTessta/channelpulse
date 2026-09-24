-- The heatmap loses no claims: cohort rows sum to the claims on window-shipped units.
with cohort as (select coalesce(sum(claims), 0) as n from {{ ref('mart_batch_claim_cohorts') }}),
facts as (
    select count(*) as n from {{ ref('fct_warranty_claims') }} where not is_legacy and ship_date is not null
)

select cohort.n as cohort_claims, facts.n as fact_claims
from cohort, facts
where cohort.n <> facts.n
