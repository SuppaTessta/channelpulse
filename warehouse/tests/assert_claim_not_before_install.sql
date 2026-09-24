-- A claim can't precede the registered install date (build prompt).
select claim_id, claim_date, install_date
from {{ ref('fct_warranty_claims') }}
where install_date is not null and claim_date < install_date
