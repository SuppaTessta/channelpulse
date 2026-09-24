select serial, mfg_date, ship_date
from {{ ref('int_serials') }}
where is_shipped and (ship_date < mfg_date or ship_date - mfg_date > 35)
