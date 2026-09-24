select
    visit_id,
    rep_id,
    distributor_id,
    visit_date,
    geofence_verified as is_geofence_verified,
    notes as visit_notes
from {{ source('raw', 'field_visits') }}
