-- Database roles for the API (PLAN §8 guardrails). Idempotent: apply as the admin user with
--   .venv/Scripts/python.exe api/app/admin.py roles
-- The runner then sets the passwords from AGENT_DB_PASSWORD / OPS_DB_PASSWORD.
--
-- channelpulse_agent  reads marts and nothing else, never writes. This role is the hard boundary for every
--                     agent and dashboard query; the SQL validator in the API is defence in depth.
-- channelpulse_ops    writes and reads ops.agent_traces, nothing else (never marts).

create schema if not exists marts;
create schema if not exists ops;

do $$
begin
    if not exists (select from pg_roles where rolname = 'channelpulse_agent') then
        create role channelpulse_agent login;
    end if;
    if not exists (select from pg_roles where rolname = 'channelpulse_ops') then
        create role channelpulse_ops login;
    end if;
end
$$;

-- nobypassrls keeps the region policies on distributor-level marts in force for the agent.
alter role channelpulse_agent with login nosuperuser nocreatedb nocreaterole noinherit noreplication nobypassrls;
alter role channelpulse_ops   with login nosuperuser nocreatedb nocreaterole noinherit noreplication nobypassrls;

alter role channelpulse_agent set default_transaction_read_only = on;
alter role channelpulse_agent set statement_timeout = '5s';
alter role channelpulse_agent set search_path = marts;

create table if not exists ops.agent_traces (
    trace_id           uuid primary key,
    created_at         timestamptz not null default now(),
    question           text not null,
    region_claim       text not null,
    model              text not null,           -- requested model
    served_model       text,                    -- model that produced the final message (differs after a refusal fallback)
    label              text not null
        check (label in ('governed_metric', 'ad_hoc_sql_verify', 'refused', 'error')),
    tool_calls         jsonb not null default '[]',  -- per call: id, name, input, output, sql, row_count, duration_ms, error
    final_sql          text[] not null default '{}',
    row_count          integer,
    input_tokens       integer not null default 0,
    output_tokens      integer not null default 0,
    cache_read_tokens  integer not null default 0,
    cache_write_tokens integer not null default 0,
    latency_ms         integer,
    est_cost_usd       numeric(10, 5) not null default 0,
    answer_text        text,
    error              text
);
create index if not exists agent_traces_created_at_idx on ops.agent_traces (created_at);  -- daily spend cap

-- PUBLIC's defaults would otherwise reach both roles: temp tables in this database and USAGE on schema public.
do $$ begin execute format('revoke temporary on database %I from public', current_database()); end $$;
revoke all on schema public from public;

-- Agent: marts only, including tables dbt creates later (it rebuilds them as this admin user).
grant usage on schema marts to channelpulse_agent;
grant select on all tables in schema marts to channelpulse_agent;
do $$
begin
    execute format(
        'alter default privileges for role %I in schema marts grant select on tables to channelpulse_agent',
        current_user);
end
$$;

-- Explicitly nothing on the other layers. Schemas that don't exist yet start with no grants anyway.
do $$
declare
    s text;
begin
    for s in select nspname from pg_namespace where nspname in ('raw', 'staging', 'intermediate', 'ops', 'public') loop
        execute format('revoke all on schema %I from channelpulse_agent', s);
        execute format('revoke all on all tables in schema %I from channelpulse_agent', s);
    end loop;
end
$$;

-- Ops: the trace table only.
revoke all on schema ops from public;
revoke all on ops.agent_traces from public;
grant usage on schema ops to channelpulse_ops;
grant insert, select on ops.agent_traces to channelpulse_ops;
revoke all on schema marts from channelpulse_ops;
revoke all on all tables in schema marts from channelpulse_ops;
