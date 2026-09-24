{#- Phase-1 RLS stub (PLAN §8): distributor-level marts only show rows for the caller's region claim.
    The API sets the claim per transaction: select set_config('app.region', '<region or ALL>', true).
    Unset or 'ALL' sees every region. The table owner (dbt) is not subject to RLS; the agent role is. -#}
{% macro apply_region_rls() %}
    alter table {{ this }} enable row level security;
    drop policy if exists region_claim on {{ this }};
    create policy region_claim on {{ this }} for select using (
        coalesce(nullif(current_setting('app.region', true), ''), 'ALL') in ('ALL', region)
    );
{% endmacro %}
