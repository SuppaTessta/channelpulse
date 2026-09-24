select claim_id, claim_date, ship_date, mfg_date
from {{ ref('fct_warranty_claims') }}
where claim_date < mfg_date or (ship_date is not null and claim_date < ship_date)
