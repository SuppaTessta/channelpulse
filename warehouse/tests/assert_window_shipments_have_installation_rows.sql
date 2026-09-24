-- Every tank shipped in the window has an installations record, registered or not (decisions D8).
select s.serial
from {{ ref('int_serials') }} as s
left join {{ ref('stg_installations') }} as i on i.serial = s.serial
where s.is_shipped and i.serial is null
