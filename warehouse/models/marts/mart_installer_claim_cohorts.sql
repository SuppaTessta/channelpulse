-- installer_claim_rate source (decisions D15): one row per installer x install month x month since install.
-- Only installer-attributed registrations count (installations.installer_id, D1). The PLAN §3 decoy test
-- compares an installer against the leave-one-out baseline of its district at equal months since install.
{{ config(indexes=[{'columns': ['installer_id']}, {'columns': ['install_district']}]) }}

with run as (
    select as_of_date from {{ ref('stg_generation_run') }}
),

installs as (
    select
        s.installer_id,
        s.install_district,
        s.install_state,
        date_trunc('month', s.install_date)::date as install_month,
        s.serial,
        s.install_date,
        s.plant_id,
        s.resin_lot_id
    from {{ ref('int_serials') }} as s
    where s.installer_id is not null and s.install_date is not null
),

cohorts as (
    select
        installer_id,
        install_district,
        install_state,
        install_month,
        count(*) as units_installed,
        count(distinct plant_id) as plants_spanned,
        count(distinct resin_lot_id) as resin_lots_spanned,
        max(install_date) as last_install_date
    from installs
    group by installer_id, install_district, install_state, install_month
),

ages as (
    select c.*, age.months_since_install
    from cohorts as c
    cross join run
    cross join lateral generate_series(
        0, floor((run.as_of_date - c.install_month) / {{ var('days_per_month') }})::int
    ) as age (months_since_install)
),

claims as (
    select
        i.installer_id,
        i.install_district,
        i.install_month,
        floor((c.claim_date - i.install_date) / {{ var('days_per_month') }})::int as months_since_install,
        count(*) as claims,
        count(*) filter (where c.failure_mode = 'base_crack') as claims_base_crack
    from {{ ref('stg_warranty_claims') }} as c
    inner join installs as i on i.serial = c.serial
    where c.claim_date >= i.install_date
    group by 1, 2, 3, 4
)

select
    a.installer_id,
    ins.installer_name,
    ins.is_certified,
    a.install_district,
    a.install_state,
    a.install_month,
    a.months_since_install,
    a.units_installed,
    a.plants_spanned,
    a.resin_lots_spanned,
    coalesce(cl.claims, 0) as claims,
    coalesce(cl.claims_base_crack, 0) as claims_base_crack,
    sum(coalesce(cl.claims, 0)) over cohort as cumulative_claims,
    round(sum(coalesce(cl.claims, 0)) over cohort * 1000.0 / a.units_installed, 2) as cumulative_claims_per_1000,
    (run.as_of_date - a.last_install_date) >= (a.months_since_install + 1) * {{ var('days_per_month') }} as is_fully_observed
from ages as a
inner join {{ ref('stg_installers') }} as ins on ins.installer_id = a.installer_id
left join claims as cl
    on cl.installer_id = a.installer_id
    and cl.install_month = a.install_month
    and cl.months_since_install = a.months_since_install
cross join run
window cohort as (partition by a.installer_id, a.install_district, a.install_month order by a.months_since_install)
