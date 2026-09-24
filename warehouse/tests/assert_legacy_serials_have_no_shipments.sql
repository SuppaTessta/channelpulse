select serial, mfg_date, ship_date
from {{ ref('int_serials') }}
where is_legacy and is_shipped
