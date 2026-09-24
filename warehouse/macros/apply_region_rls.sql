{#- Phase-1 RLS stub (PLAN §8): distributor-level marts only show rows for the caller's region claim.
    The API sets the claim per transaction: select set_config('app.region', '<region or ALL>', true).
    Unset or 'ALL' sees every region. The table owner (dbt) is not subject to RLS; the agent role is.
    via_distributor: for narrow tables without a region column, look the region up on dim_distributor
    (itself RLS-filtered). The model must declare `-- depends_on: {{ ref('dim_distributor') }}`. -#}
{% macro apply_region_rls(via_distributor=false) %}
    alter table {{ this }} enable row level security;
    drop policy if exists region_claim on {{ this }};
    create policy region_claim on {{ this }} for select using (
    {%- if via_distributor %}
        coalesce(nullif(current_setting('app.region', true), ''), 'ALL') = 'ALL'
        or distributor_id in (
            select d.distributor_id from {{ ref('dim_distributor') }} as d
            where d.region = current_setting('app.region', true)
        )
    {%- else %}
        coalesce(nullif(current_setting('app.region', true), ''), 'ALL') in ('ALL', region)
    {%- endif %}
    );
{% endmacro %}
