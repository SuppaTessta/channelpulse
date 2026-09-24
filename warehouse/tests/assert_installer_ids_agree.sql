-- The technician-recorded installer on a claim matches the installation record whenever both exist (D1).
select c.claim_id, c.installer_id as claim_installer_id, i.installer_id as installation_installer_id
from {{ ref('stg_warranty_claims') }} as c
inner join {{ ref('stg_installations') }} as i on i.serial = c.serial
where c.installer_id is not null and i.installer_id is not null and c.installer_id <> i.installer_id
