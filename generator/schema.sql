-- Raw landing schema (CHANNELPULSE_PLAN.md §2 + docs/decisions.md D1–D8).
-- Recreated from scratch by every `make seed`. PKs, NOT NULLs and enum CHECKs live here;
-- cross-table relationships are asserted as dbt tests, as is usual for a landing layer.

create table raw.generation_run (
    as_of_date      date        not null,  -- last simulated day with data
    anchor_date     date        not null,  -- pins month 1..36 (config.yaml)
    seed            bigint      not null,
    generated_at    timestamptz not null default now()
);

create table raw.geo_pincodes (                -- D4
    pincode   text primary key,
    district  text not null,
    state     text not null,
    region    text not null
);

create table raw.plants (
    plant_id    text primary key,
    name        text not null,
    city        text not null,
    state       text not null,
    plant_type  text not null
);

create table raw.products (
    sku              text primary key,
    name             text not null,
    category         text not null check (category in ('tank', 'pipe', 'fitting', 'sanitaryware')),
    capacity_l       integer,
    list_price_inr   numeric(12, 2) not null,
    warranty_months  integer not null,
    launched_date    date not null
);

create table raw.production_batches (
    batch_id       text primary key,
    plant_id       text not null,
    sku            text not null,
    line_no        smallint not null,
    shift          text not null,
    mfg_date       date not null,
    resin_lot_id   text not null,
    qty_produced   integer not null check (qty_produced > 0),
    qc_pass_rate   numeric(5, 4) not null check (qc_pass_rate between 0 and 1)
);

create table raw.serial_units (                -- D3: tanks only
    serial    text primary key,
    batch_id  text not null,
    sku       text not null,
    mfg_date  date not null
);

create table raw.sales_reps (
    rep_id     text primary key,
    name       text not null,
    region     text not null,
    hire_date  date not null
);

create table raw.distributors (
    distributor_id    text primary key,
    name              text not null,
    tier              text not null,
    state             text not null,
    district          text not null,
    pincode           text not null,
    onboarding_date   date not null,
    credit_limit_inr  numeric(14, 2) not null,
    sales_rep_id      text not null,
    status            text not null
);

create table raw.retailers (
    retailer_id      text primary key,
    distributor_id   text not null,
    name             text not null,
    pincode          text not null,
    onboarding_date  date not null
);

create table raw.opening_channel_stock (       -- D5
    distributor_id  text not null,
    sku             text not null,
    qty             integer not null check (qty >= 0),
    as_of_date      date not null,
    primary key (distributor_id, sku)
);

create table raw.schemes (
    scheme_id            text primary key,
    name                 text not null,
    start_date           date not null,
    end_date             date not null,
    discount_pct         numeric(5, 4) not null,
    min_slab_units       integer not null,
    applies_to_category  text not null,
    check (end_date >= start_date)
);

create table raw.primary_invoices (
    invoice_id        text primary key,
    distributor_id    text not null,
    invoice_date      date not null,
    scheme_id         text,
    total_amount_inr  numeric(14, 2) not null,
    due_date          date not null
);

create table raw.primary_invoice_lines (
    line_id         bigint primary key,
    invoice_id      text not null,
    sku             text not null,
    qty             integer not null check (qty > 0),
    unit_price_inr  numeric(12, 2) not null,
    batch_id        text                      -- D6: null only for sanitaryware
);

create table raw.secondary_sales (
    record_id       bigint primary key,
    distributor_id  text not null,
    retailer_id     text,                     -- null = counter/unattributed sale
    sku             text not null,
    sale_date       date not null,
    qty             integer not null check (qty > 0),
    reported_date   date not null,
    source          text not null
);

create table raw.shipments (
    shipment_id     bigint primary key,
    serial          text,                     -- null = bulk dispatch of non-serialised goods
    distributor_id  text not null,
    ship_date       date not null
);

create table raw.installers (
    installer_id  text primary key,
    name          text not null,
    district      text not null,
    certified     boolean not null
);

create table raw.installations (
    serial          text primary key,
    pincode         text,                     -- D8: null until registered
    install_date    date,
    registered_via  text,
    installer_id    text,                     -- D1
    _loaded_at      date not null             -- D16: registration date if registered, else ship date
);

create table raw.warranty_claims (
    claim_id          text primary key,
    serial            text not null,
    claim_date        date not null,
    failure_mode      text not null check (failure_mode in ('base_crack', 'leak', 'fitting_failure', 'discoloration', 'other')),
    cost_inr          numeric(12, 2) not null,
    status            text not null,
    technician_notes  text,
    installer_id      text
);

create table raw.collections (
    collection_id  bigint primary key,
    invoice_id     text not null,
    payment_date   date not null,
    amount_inr     numeric(14, 2) not null check (amount_inr > 0)
);

create table raw.field_visits (
    visit_id           bigint primary key,
    rep_id             text not null,
    distributor_id     text not null,
    visit_date         date not null,
    geofence_verified  boolean not null,
    notes              text
);
