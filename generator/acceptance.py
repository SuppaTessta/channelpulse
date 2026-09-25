"""Black-box acceptance suite for the ChannelPulse generator.

Proves or disproves, with SQL against the loaded schemas, that each planted anomaly in
generator/ground_truth.yaml is in the data as specified and that nothing else gives it away.
It never imports or reads the generator's code; it only runs its CLI to build the comparison
schemas (one anomaly disabled each, a repeat run, and an earlier as-of).

    .venv\\Scripts\\python.exe generator/acceptance.py [--regenerate] [--checks G1,R2,...]

Prints a results table, writes generator/acceptance_report.json and exits 1 if any
non-deferred check fails.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import psycopg
import yaml

HERE = Path(__file__).resolve().parent
GT = yaml.safe_load((HERE / "ground_truth.yaml").read_text(encoding="utf-8"))
CFG = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
DETECTORS = yaml.safe_load((HERE.parent / "detectors" / "detectors.yaml").read_text(encoding="utf-8"))
REPORT = HERE / "acceptance_report.json"

AS_OF = GT["anchor"]["as_of"]
AS_OF_ALT = date(2026, 9, 9)
WINDOW_START = GT["anchor"]["window_start"]
LOT = GT["anomalies"]["resin_lot"]
CHURN = GT["anomalies"]["distributor_churn"]
STUFF = GT["anomalies"]["quarter_end_stuffing"]
DECOY = GT["anomalies"]["installer_decoy"]
NORTH_BENGAL = CFG["geography"]["north_bengal_districts"]

# schema -> extra CLI args; `raw` is the full run and must already exist (built only if missing)
SCHEMAS = {
    "raw": [],
    "raw_cf_resin_lot": ["--disable", "resin_lot"],
    "raw_cf_distributor_churn": ["--disable", "distributor_churn"],
    "raw_cf_quarter_end_stuffing": ["--disable", "quarter_end_stuffing"],
    "raw_cf_installer_decoy": ["--disable", "installer_decoy"],
    "raw_repeat": [],
    "raw_asof": ["--as-of", AS_OF_ALT.isoformat()],
}
PG = {
    "host": os.environ.get("POSTGRES_HOST", "127.0.0.1"),  # not localhost: IPv6-first stalls on Windows
    "port": os.environ.get("POSTGRES_PORT", "5432"),
    "user": os.environ.get("POSTGRES_USER", "channelpulse"),
    "password": os.environ.get("POSTGRES_PASSWORD", "channelpulse"),
    "dbname": os.environ.get("POSTGRES_DB", "channelpulse"),
}
TELL_WORDS = ["bad", "defect", "anomal", "decoy", "stuff", "churn", "fraud", "planted", "fake", "synthetic", "inject",
              "dummy", "suspicious", "outlier", "faulty", "contaminat", "recall", "counterfactual", "hazard", "multiplier",
              "test", "flagged", "ground_truth", "ground truth", "groundtruth", "resin_lot_bad"]
TELL_RE = re.compile(r"(?<![a-z])(" + "|".join(map(re.escape, TELL_WORDS)) + ")", re.IGNORECASE)  # word-start match


# ---------------------------------------------------------------- helpers

def rows(db, sql, **params):
    return db.execute(sql, params).fetchall()


def one(db, sql, **params):
    return db.execute(sql, params).fetchone()


def result(cid, ok, measured, target, evidence, **detail):
    return {"id": cid, "status": "PASS" if ok else "FAIL", "measured": measured, "target": target,
            "evidence": evidence, "detail": detail}


def deferred(cid, target, reason):
    return {"id": cid, "status": "DEFERRED", "measured": "-", "target": target, "evidence": reason, "detail": {}}


def within(x, lo, hi):
    return x is not None and lo <= x <= hi


def ratio(a, b):
    return a / b if b else None


def fmt(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def rate_ratio_ci(a, n1, b, n2):
    """Rate ratio (a/n1)/(b/n2) with a 95% log-normal CI; None when either count is zero."""
    if not (a and b and n1 and n2):
        return None, None, None
    rr = (a / n1) / (b / n2)
    se = math.sqrt(1 / a + 1 / b)
    return rr, rr * math.exp(-1.96 * se), rr * math.exp(1.96 * se)


def month_add(m, k):
    i = m.year * 12 + m.month - 1 + k
    return date(i // 12, i % 12 + 1, 1)


def fy_bounds(label):  # "FY25" -> 2024-04-01..2025-03-31 (fiscal_year: start_month 4, label end_year)
    end_year = 2000 + int(label[2:])
    return date(end_year - 1, 4, 1), date(end_year, 3, 31)


def dedup(s):
    """Secondary rows minus re-sent uploads: the later copy of an identical sale row."""
    return (f"(select * from (select x.*, row_number() over (partition by distributor_id, retailer_id, sku,"
            f" sale_date, qty order by reported_date, record_id) as dup_rank from {s}.secondary_sales x) d"
            f" where dup_rank = 1)")


def schema_ready(db, s):
    ok = one(db, "select to_regclass(%(t)s) is not null", t=f"{s}.generation_run")[0]
    return ok and one(db, f"select count(*) from {s}.generation_run")[0] == 1


def raw_tables(db, s="raw"):
    return [r[0] for r in rows(db, "select table_name from information_schema.tables where table_schema = %(s)s"
                                   " and table_type = 'BASE TABLE' order by 1", s=s)]


def columns(db, table, exclude=()):
    cols = [r[0] for r in rows(db, "select column_name from information_schema.columns where table_schema = 'raw'"
                                   " and table_name = %(t)s order by ordinal_position", t=table)]
    return [c for c in cols if c not in exclude]


# ---------------------------------------------------------------- generation

def ensure_schemas(db, regenerate):
    env = {**os.environ, "POSTGRES_HOST": PG["host"], "POSTGRES_PORT": PG["port"], "POSTGRES_USER": PG["user"],
           "POSTGRES_PASSWORD": PG["password"], "POSTGRES_DB": PG["dbname"]}
    log = {}
    for s, args in SCHEMAS.items():
        if schema_ready(db, s) and (s == "raw" or not regenerate):
            log[s] = {"generated_this_run": False, "seconds": 0.0}
            continue
        print(f"generating {s} {' '.join(args)} ...", flush=True)
        t0 = time.perf_counter()
        cmd = [sys.executable, str(HERE / "generate.py"), "--schema", s, *args]
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
        if proc.returncode:
            sys.exit(f"generation of {s} failed ({proc.returncode}):\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
        log[s] = {"generated_this_run": True, "seconds": round(time.perf_counter() - t0, 1)}
    for s in SCHEMAS:
        a, anchor, seed = one(db, f"select as_of_date, anchor_date, seed from {s}.generation_run")
        log[s].update(as_of=a.isoformat(), anchor=anchor.isoformat(), seed=seed)
    return log


# ---------------------------------------------------------------- global

def check_g1(db):
    counts = {t: one(db, f"select count(*) from raw.{t}")[0] for t in raw_tables(db)}
    mb = float(one(db, "select sum(pg_total_relation_size(oid)) / 1048576.0 from pg_class"
                       " where relnamespace = 'raw'::regnamespace and relkind = 'r'")[0])
    total = sum(counts.values())
    top = ", ".join(f"{t} {n:,}" for t, n in sorted(counts.items(), key=lambda kv: -kv[1])[:4])
    return [result("G1", within(total, 1_750_000, 1_950_000), f"{total:,} rows", "1.75M-1.95M",
                   f"{len(counts)} tables, {mb:.0f} MB total relation size; largest: {top}",
                   total=total, size_mb=round(mb, 1), per_table=counts)]


def table_hash(db, s, table):
    expr = "(t.as_of_date, t.anchor_date, t.seed)::text" if table == "generation_run" else "t::text"
    return one(db, f"select md5(coalesce(string_agg(h, '' order by h), '')), count(*)"
                   f" from (select md5({expr}) h from {s}.{table} t) x")


def check_g2(db):
    tables = raw_tables(db)
    diff = []
    for t in tables:
        a, b = table_hash(db, "raw", t), table_hash(db, "raw_repeat", t)
        if a != b:
            diff.append(f"{t} ({a[1]} vs {b[1]} rows)")
    same_tables = tables == raw_tables(db, "raw_repeat")
    ok = not diff and same_tables
    return [result("G2", ok, f"{len(tables) - len(diff)}/{len(tables)} tables identical", "all identical",
                   "order-independent md5 per table, generation_run.generated_at exempt; "
                   + ("differs: " + "; ".join(diff) if diff else "no differences"), differing=diff)]


def g3_specs(db):
    """(label, table, columns, raw-side filter, as-of-side filter). %(d)s is the earlier as-of."""
    d = "%(d)s::date"
    ev = {
        "production_batches": f"mfg_date <= {d}",
        "serial_units": f"mfg_date <= {d}",
        "primary_invoices": f"invoice_date <= {d}",
        "primary_invoice_lines": f"invoice_id in (select invoice_id from {{s}}.primary_invoices where invoice_date <= {d})",
        "secondary_sales": f"reported_date <= {d}",
        "shipments": f"ship_date <= {d}",
        "warranty_claims": f"claim_date <= {d}",
        "collections": f"payment_date <= {d}",
        "field_visits": f"visit_date <= {d}",
        "retailers": f"onboarding_date <= {d}",
        "schemes": f"start_date <= {d}",
    }
    excluded = {"products": ["list_price_inr"], "distributors": ["status"], "warranty_claims": ["status"]}
    specs = []
    for t in raw_tables(db):
        if t in ("generation_run", "installations"):
            continue
        cols = ", ".join(columns(db, t, excluded.get(t, ())))
        specs.append((t, t, cols, ev.get(t, "true"), "true"))
    specs.append(("installations (serials shipped by D)", "installations", "serial",
                  f"serial in (select serial from {{s}}.shipments where ship_date <= {d})", "true"))
    specs.append(("installations (registered by D)", "installations", "*",
                  f"install_date is not null and _loaded_at <= {d}", "install_date is not null"))
    return specs


def check_g3(db):
    bad, per = [], {}
    for label, t, cols, fr, fa in g3_specs(db):
        a = f"select {cols} from raw.{t} where {fr.format(s='raw')}"
        b = f"select {cols} from raw_asof.{t} where {fa.format(s='raw_asof')}"
        only_raw, only_asof, n = one(db, f"select (select count(*) from ({a} except all {b}) x),"
                                         f" (select count(*) from ({b} except all {a}) y), (select count(*) from ({a}) z)",
                                     d=AS_OF_ALT)
        per[label] = {"rows": n, "only_in_raw": only_raw, "only_in_raw_asof": only_asof}
        if only_raw or only_asof:
            bad.append(f"{label}: {only_raw} only in raw, {only_asof} only in raw_asof of {n}")
    mism = sum(v["only_in_raw"] + v["only_in_raw_asof"] for v in per.values())
    return [result("G3", not bad, f"{mism:,} mismatched rows", "0",
                   f"{len(per)} comparisons at D={AS_OF_ALT}; excluded time-varying columns: products.list_price_inr,"
                   " distributors.status, warranty_claims.status, registration fields of units not registered by D; "
                   + ("; ".join(bad) if bad else "all equal"), per_table=per)]


def check_g4(db):
    facts = [("production_batches", "mfg_date"), ("serial_units", "mfg_date"), ("primary_invoices", "invoice_date"),
             ("secondary_sales", "sale_date"), ("secondary_sales", "reported_date"), ("shipments", "ship_date"),
             ("installations", "install_date"), ("installations", "_loaded_at"), ("warranty_claims", "claim_date"),
             ("collections", "payment_date"), ("field_visits", "visit_date"), ("distributors", "onboarding_date"),
             ("retailers", "onboarding_date"), ("schemes", "start_date"), ("opening_channel_stock", "as_of_date"),
             ("sales_reps", "hire_date"), ("products", "launched_date")]
    as_of = one(db, "select as_of_date from raw.generation_run")[0]
    late, maxes = {}, {}
    for t, c in facts:
        n, mx = one(db, f"select count(*) filter (where {c} > %(a)s), max({c}) from raw.{t}", a=as_of)
        maxes[f"{t}.{c}"] = str(mx)
        if n:
            late[f"{t}.{c}"] = n
    total = sum(late.values())
    latest = max(maxes.values())
    return [result("G4", total == 0 and as_of == AS_OF, f"{total} rows after as-of", "0",
                   f"generation_run.as_of_date={as_of}; latest fact date {latest} across {len(facts)} date columns"
                   + (f"; late: {late}" if late else ""), late=late, max_dates=maxes)]


def exclusive_values(db, lot, ins, dist):
    """Text values that occur only on rows tied to a planted entity (a marker beyond the id)."""
    lot_serials = ("serial in (select su.serial from raw.serial_units su join raw.production_batches b"
                   " using (batch_id) where b.resin_lot_id = %(lot)s)")
    ins_serials = "serial in (select serial from raw.installations where installer_id = %(ins)s)"
    probes = [
        ("production_batches", "resin_lot_id = %(lot)s", ["shift", "sku", "plant_id"]),
        ("warranty_claims", lot_serials, ["failure_mode", "status", "technician_notes"]),
        ("warranty_claims", ins_serials, ["failure_mode", "status", "technician_notes", "installer_id"]),
        ("installations", "installer_id = %(ins)s", ["registered_via"]),
        ("installers", "installer_id = %(ins)s", ["district"]),
        ("distributors", "distributor_id = %(dist)s", ["tier", "state", "district", "sales_rep_id", "status"]),
        ("secondary_sales", "distributor_id = %(dist)s", ["source"]),
        ("field_visits", "distributor_id = %(dist)s", ["notes", "rep_id"]),
    ]
    hits = []
    for t, pred, cols in probes:
        for c in cols:
            if c == "installer_id":  # the id itself is allowed to mark the entity
                continue
            for v, n in rows(db, f"select v, count(*) from (select {c}::text v, ({pred}) p from raw.{t}) x"
                                 f" where v is not null group by v having bool_and(p)", lot=lot, ins=ins, dist=dist):
                hits.append(f"{t}.{c}={v!r} ({n} rows)")
    return hits


def check_g5(db):
    text_cols = {}
    for t, c in rows(db, "select table_name, column_name from information_schema.columns where table_schema = 'raw'"
                         " and data_type in ('text', 'character varying') order by 1, 2"):
        text_cols.setdefault(t, []).append(c)
    vocab, substr = {}, {}
    for t, cols in text_cols.items():  # LIKE prefilter per table (fast), then a word-start regex per value
        for rec in rows(db, f"select {', '.join(cols)} from raw.{t} where lower(concat_ws(' ', {', '.join(cols)}))"
                            " like any(%(p)s) limit 2000", p=[f"%{w}%" for w in TELL_WORDS]):
            for c, v in zip(cols, rec):
                if v is not None and any(w in v.lower() for w in TELL_WORDS):
                    bucket = vocab if TELL_RE.search(v) else substr
                    bucket[f"{t}.{c}={v!r}"] = bucket.get(f"{t}.{c}={v!r}", 0) + 1
    vocab = [f"{k} x{n}" for k, n in vocab.items()]
    lot, ins, dist = LOT["resin_lot_id"], DECOY["installer_id"], CHURN["distributor_id"]
    excl = exclusive_values(db, lot, ins, dist)
    qc_lot, qc_lo, qc_hi = one(db, """
        with l as (select resin_lot_id, avg(qc_pass_rate) q from raw.production_batches
                   where plant_id = 'DGP' and line_no = 2 group by 1)
        select (select q from l where resin_lot_id = %(lot)s), min(q), max(q) from l""", lot=lot)
    inst = one(db, """select count(*), count(*) filter (where n > (select count(*) from raw.installations
                        where installer_id = %(ins)s)) from (select installer_id, count(*) n from raw.installations
                        where installer_id is not null group by 1) x""", ins=ins)
    ok = not vocab and not excl
    return [result("G5", ok, f"{len(vocab)} vocabulary hits, {len(excl)} planted-only values", "0 and 0",
                   f"{sum(map(len, text_cols.values()))} text columns in {len(text_cols)} tables scanned for"
                   f" {len(TELL_WORDS)} stems; {len(substr)} values contain a stem mid-word (not tells); "
                   + (f"vocabulary: {vocab}; " if vocab else "")
                   + (f"planted-only values: {excl}; " if excl else "")
                   + f"lot qc_pass_rate mean {qc_lot:.4f} inside DGP-L2 lot range [{qc_lo:.4f}, {qc_hi:.4f}]; "
                   f"note: {ins} has more installs than {inst[0] - inst[1] - 1} of {inst[0] - 1} other installers"
                   " (volume is specified, not a text tell)",
                   vocabulary_hits=vocab, mid_word_matches=list(substr), planted_only_values=excl)]


def check_g6(db):
    a = AS_OF
    out = []
    reg90, n90 = one(db, """select avg((i.install_date is not null and i.install_date <= s.ship_date + 90)::int), count(*)
                            from raw.shipments s join raw.installations i using (serial)
                            where s.ship_date <= %(a)s::date - 90""", a=a)
    out.append(result("G6a", within(float(reg90), 0.60, 0.70), f"{float(reg90):.1%}", "60-70%",
                      f"install_date within 90 d of ship over {n90:,} serials shipped <= as_of-90",
                      value=float(reg90), units=n90))
    never, never_mat, n_all = one(db, """select avg((i.install_date is null)::int),
                                         avg((i.install_date is null)::int) filter (where s.ship_date <= %(a)s::date - 150),
                                         count(*) from raw.shipments s join raw.installations i using (serial)""", a=a)
    out.append(result("G6b", within(float(never), 0.30, 0.40), f"{float(never):.1%}", "30-40%",
                      f"never registered over all {n_all:,} in-window shipped tanks; {float(never_mat):.1%} over"
                      " shipments >= 150 d old (registration fate resolved: 120 d install cap + 30 d visibility)",
                      value=float(never), matured=float(never_mat)))
    p80, p97, lag_max = one(db, f"""select percentile_disc(0.80) within group (order by reported_date - sale_date),
                                    percentile_disc(0.97) within group (order by reported_date - sale_date),
                                    (select max(reported_date - sale_date) from raw.secondary_sales)
                                    from {dedup('raw')} d where sale_date <= %(a)s::date - 35""", a=a)
    out.append(result("G6c", within(p80, 6, 8) and within(p97, 19, 23) and lag_max <= 35,
                      f"p80 {p80} d, p97 {p97} d, max {lag_max} d", "p80 7+-1, p97 21+-2, max <= 35",
                      "reported_date - sale_date over de-duplicated rows with sale_date <= as_of-35 (uncensored);"
                      " max over all rows", p80=p80, p97=p97, max=lag_max))
    dups, total, gap_lo, gap_hi = one(db, """
        with r as (select reported_date, row_number() over w rn, min(reported_date) over w r0
                   from raw.secondary_sales window w as (partition by distributor_id, retailer_id, sku, sale_date, qty
                   order by reported_date, record_id))
        select count(*) filter (where rn > 1), count(*), min(reported_date - r0) filter (where rn > 1),
               max(reported_date - r0) filter (where rn > 1) from r""")
    share = dups / total
    out.append(result("G6d", within(share, 0.004, 0.006), f"{share:.2%}", "about 0.5% (0.4-0.6%)",
                      f"{dups:,} of {total:,} rows repeat an earlier identical sale row, re-sent {gap_lo}-{gap_hi} d later",
                      value=share, duplicates=dups))
    shared, n_ret, shared_norm = one(db, """
        select count(*) filter (where n > 1), count(*), count(*) filter (where nn > 1)
        from (select count(*) over (partition by name) n,
                     count(*) over (partition by lower(regexp_replace(name, '[^A-Za-z0-9]', '', 'g'))) nn
              from raw.retailers) x""")
    out.append(result("G6e", within(shared / n_ret, 0.02, 0.04), f"{shared / n_ret:.1%}", "about 3% (2-4%)",
                      f"{shared} of {n_ret:,} retailers share an exact name with another retailer;"
                      f" {shared_norm / n_ret:.1%} ignoring case and punctuation",
                      value=shared / n_ret, normalised=shared_norm / n_ret))
    rev, tanks = {}, {}
    for fy in ("FY25", "FY26"):
        lo, hi = fy_bounds(fy)
        rev[fy] = float(one(db, """select sum(l.qty * l.unit_price_inr) / 1e7 from raw.primary_invoice_lines l
                                   join raw.primary_invoices i using (invoice_id)
                                   where i.invoice_date between %(lo)s and %(hi)s""", lo=lo, hi=hi)[0])
        tanks[fy] = one(db, "select count(*) from raw.shipments where serial is not null"
                            " and ship_date between %(lo)s and %(hi)s", lo=lo, hi=hi)[0]
    out.append(result("G6f", all(within(v, 450, 500) for v in rev.values()),
                      ", ".join(f"{k} Rs {v:.1f} cr" for k, v in rev.items()), "Rs 450-500 cr per FY",
                      "sum(qty x unit_price_inr) of primary invoice lines by invoice_date", **rev))
    out.append(result("G6g", all(within(v, 93_500, 126_500) for v in tanks.values()),
                      ", ".join(f"{k} {v:,}" for k, v in tanks.items()), "110k +-15% (93.5k-126.5k)",
                      "serialised tank shipments by ship_date per fiscal year", **tanks))
    return out


def check_g7(db):
    n_bad, n_cells, worst, n_days = one(db, f"""
        with f as (
            select distributor_id, sku, as_of_date d, qty q from raw.opening_channel_stock
            union all
            select i.distributor_id, l.sku, i.invoice_date, l.qty from raw.primary_invoice_lines l
            join raw.primary_invoices i using (invoice_id)
            union all
            select distributor_id, sku, sale_date, -qty from {dedup('raw')} s),
        day as (select distributor_id, sku, d, sum(q) q from f group by 1, 2, 3),
        bal as (select distributor_id, sku, sum(q) over (partition by distributor_id, sku order by d) b from day)
        select count(*) filter (where b < 0), count(distinct (distributor_id, sku)) filter (where b < 0), min(b), count(*)
        from bal""")
    return [result("G7", n_bad == 0, f"{n_bad} negative cell-days", "0",
                   f"opening + cumulative primary (invoice_date) - cumulative de-duplicated secondary (sale_date),"
                   f" end of day, over {n_days:,} distributor x sku x event-days; {n_cells} cells ever negative,"
                   f" minimum balance {worst}", negative_days=n_bad, cells=n_cells, min_balance=worst)]


# ---------------------------------------------------------------- resin lot

def lot_claims(db, s, lots, modes, horizon=365):
    """(shipped units with >= horizon days since ship, claims of `modes` within horizon of ship)."""
    return one(db, f"""
        with u as (select su.serial, sh.ship_date from {s}.serial_units su
                   join {s}.production_batches b using (batch_id) join {s}.shipments sh on sh.serial = su.serial
                   where b.resin_lot_id = any(%(lots)s) and sh.ship_date <= %(a)s::date - %(h)s)
        select (select count(*) from u),
               (select count(*) from u join {s}.warranty_claims c using (serial)
                where c.failure_mode = any(%(m)s) and c.claim_date < u.ship_date + %(h)s)""",
               lots=list(lots), m=list(modes), a=AS_OF, h=horizon)


def peer_lots(db, s):
    return [r[0] for r in rows(db, f"""
        select resin_lot_id from {s}.production_batches where plant_id = 'DGP' and line_no = %(line)s
        group by 1 having min(mfg_date) >= %(f)s::date - interval '12 months' and min(mfg_date) < %(f)s
        order by 1""", line=LOT["line_no"], f=LOT["first_use_date"])]


def dgp_base_crack_monthly(db, s):
    return dict(rows(db, f"""select date_trunc('month', c.claim_date)::date, count(*) from {s}.warranty_claims c
                             join {s}.serial_units su using (serial) join {s}.production_batches b using (batch_id)
                             where b.plant_id = 'DGP' and c.failure_mode = 'base_crack' group by 1"""))


def check_r1(db):
    code = one(db, "select plant_id from raw.plants where city = %(c)s", c=LOT["plant"])[0]
    expected = f"RL-{code}-L{LOT['line_no']}-{LOT['first_use_date']:%y%m%d}"
    places, first, last, n_days, units = one(db, """
        select array_agg(distinct plant_id || '-' || line_no), min(mfg_date), max(mfg_date), count(distinct mfg_date),
               (select count(*) from raw.serial_units su join raw.production_batches b2 using (batch_id)
                where b2.resin_lot_id = %(lot)s)
        from raw.production_batches where resin_lot_id = %(lot)s""", lot=expected)
    span = [LOT["first_use_date"] + timedelta(k) for k in range((LOT["last_mfg_date"] - LOT["first_use_date"]).days + 1)]
    prod_days = sum(d.weekday() < 6 for d in span)
    overlap = one(db, """select count(distinct resin_lot_id) from raw.production_batches
                         where plant_id = %(p)s and line_no = %(l)s and resin_lot_id <> %(lot)s
                         and mfg_date between %(f)s and %(t)s""",
                  p=code, l=LOT["line_no"], lot=expected, f=LOT["first_use_date"], t=LOT["last_mfg_date"])[0]
    ok = (expected == LOT["resin_lot_id"] and places == [f"{code}-{LOT['line_no']}"]
          and first == LOT["first_use_date"] and last == LOT["last_mfg_date"] and n_days == prod_days
          and within(units, 2600, 4000) and overlap == 0)
    return [result("R1", ok, f"{expected}: {units:,} units", "rule id; [2600, 4000] units; exclusive",
                   f"used on {places} {first}..{last} on {n_days}/{prod_days} Mon-Sat days; {overlap} other"
                   f" {code}-L{LOT['line_no']} lots overlap; ground truth id {LOT['resin_lot_id']}",
                   lot_id=expected, units=units, production_days=n_days, overlapping_lots=overlap)]


def check_r2_r3(db):
    lot = LOT["resin_lot_id"]
    out, detail = [], {}
    other = ["leak", "fitting_failure", "discoloration", "other"]
    for s in ("raw", "raw_cf_resin_lot"):
        peers = peer_lots(db, s)
        for key, modes in (("base_crack", ["base_crack"]), ("other_modes", other)):
            n1, a = lot_claims(db, s, [lot], modes)
            n2, b = lot_claims(db, s, peers, modes)
            rr, lo, hi = rate_ratio_ci(a, n1, b, n2)
            detail[(s, key)] = {"lot_units": n1, "lot_claims": a, "peer_units": n2, "peer_claims": b,
                                "peer_lots": len(peers), "ratio": rr, "ci95": [lo, hi]}

    def ev(s, key):
        d = detail[(s, key)]
        return (f"{s}: lot {d['lot_claims']}/{d['lot_units']:,} = {1000 * d['lot_claims'] / d['lot_units']:.1f}/1000"
                f" vs {d['peer_lots']} peer lots {d['peer_claims']}/{d['peer_units']:,}"
                f" = {1000 * d['peer_claims'] / d['peer_units']:.1f}/1000, ratio {fmt(d['ratio'], 2)}"
                f" (95% CI {fmt(d['ci95'][0], 2)}-{fmt(d['ci95'][1], 2)})")

    r_raw, r_cf = detail[("raw", "base_crack")]["ratio"], detail[("raw_cf_resin_lot", "base_crack")]["ratio"]
    out.append(result("R2", r_raw is not None and r_raw >= 3.0 and within(r_cf, 0.6, 1.6),
                      f"{fmt(r_raw, 2)}x (cf {fmt(r_cf, 2)}x)", ">= 3.0x; cf [0.6, 1.6]",
                      ev("raw", "base_crack") + "; " + ev("raw_cf_resin_lot", "base_crack"),
                      **{f"{s}.{k}": v for (s, k), v in detail.items() if k == "base_crack"}))
    o_raw = detail[("raw", "other_modes")]["ratio"]
    out.append(result("R3", within(o_raw, 0.6, 1.6), f"{fmt(o_raw, 2)}x", "[0.6, 1.6]",
                      ev("raw", "other_modes"), **{f"{s}.{k}": v for (s, k), v in detail.items() if k == "other_modes"}))
    return out


def check_r4(db):
    raw, cf = dgp_base_crack_monthly(db, "raw"), dgp_base_crack_monthly(db, "raw_cf_resin_lot")
    base = [raw.get(month_add(date(2024, 10, 1), k), 0) for k in range(6)]
    plateau = [month_add(date(2025, 8, 1), k) for k in range(8)]
    up = 100 * (sum(raw.get(m, 0) for m in plateau) / sum(cf.get(m, 0) for m in plateau) - 1)
    m21_31 = [month_add(date(2025, 6, 1), k) for k in range(11)]
    up_gt = 100 * (sum(raw.get(m, 0) for m in m21_31) / sum(cf.get(m, 0) for m in m21_31) - 1)
    lo, hi = LOT["expected"]["plateau_uplift_pct"]
    mean_base = statistics.mean(base)
    return [result("R4", mean_base >= 40 and within(up, lo, hi), f"baseline {mean_base:.1f}/mo, uplift {up:.1f}%",
                   f">= 40/mo; uplift [{lo}, {hi}]%",
                   f"Durgapur base_crack by claim month; 2024-10..2025-03 {base}; 2025-08..2026-03 raw"
                   f" {sum(raw.get(m, 0) for m in plateau)} vs cf {sum(cf.get(m, 0) for m in plateau)};"
                   f" ground-truth span m21-m31 (2025-06..2026-04) uplift {up_gt:.1f}%",
                   baseline=base, uplift_pct=up, uplift_m21_m31_pct=up_gt,
                   raw={str(k): v for k, v in sorted(raw.items())}, cf={str(k): v for k, v in sorted(cf.items())})]


def check_r5(db):
    ship, inst, off_footprint = one(db, """
        with l2 as (select su.serial from raw.serial_units su join raw.production_batches b using (batch_id)
                    where b.plant_id = 'DGP' and b.line_no = 2)
        select (select count(*) from raw.shipments sh join l2 using (serial) join raw.distributors d using (distributor_id)
                where d.state = 'Assam' or d.district = any(%(nb)s)),
               (select count(*) from raw.installations i join l2 using (serial) join raw.geo_pincodes g using (pincode)
                where g.state = 'Assam' or g.district = any(%(nb)s)),
               (select count(*) from raw.shipments sh join l2 using (serial) join raw.distributors d using (distributor_id)
                where d.state <> all(%(fp)s))""",
                                     nb=NORTH_BENGAL, fp=GT["calibration"]["durgapur_line2"]["footprint_states"])
    return [result("R5", ship == 0 and inst == 0, f"{ship} shipped, {inst} installed", "0 and 0",
                   f"Durgapur Line 2 serials to Assam / North Bengal ({len(NORTH_BENGAL)} districts) distributors or"
                   f" installation pincodes; {off_footprint} shipped outside the WB/JH/BR/OD footprint",
                   shipped=ship, installed=inst, outside_footprint=off_footprint)]


def cusum(series, first, last):
    """Standardised one-sided CUSUM per detectors.yaml case_study_comparator; returns (alarm month, path)."""
    spec = DETECTORS["case_study_comparator"]
    k, h = spec["k"], spec["h"]
    s, alarm, path, m = 0.0, None, [], first
    while m <= last:
        mu = statistics.mean(series.get(month_add(m, -j), 0) for j in range(4, 16))
        s = max(0.0, s + (series.get(m, 0) - mu) / math.sqrt(mu) - k)
        path.append((str(m)[:7], series.get(m, 0), round(mu, 1), round(s, 2)))
        if alarm is None and s > h:
            alarm = m
        m = month_add(m, 1)
    return alarm, path


def check_r6(db):
    first = month_add(date(WINDOW_START.year, WINDOW_START.month, 1), 16)  # window month 17
    last = month_add(date(AS_OF.year, AS_OF.month, 1), -1 if (AS_OF + timedelta(1)).day != 1 else 0)
    a_raw, p_raw = cusum(dgp_base_crack_monthly(db, "raw"), first, last)
    a_cf, p_cf = cusum(dgp_base_crack_monthly(db, "raw_cf_resin_lot"), first, last)
    lo, hi = LOT["expected"]["raw_cusum_alarm_month"]["range"]
    alarm = str(a_raw)[:7] if a_raw else "never"
    return [result("R6", a_raw is not None and a_raw <= last and a_cf is None,
                   f"alarm {alarm} (cf {'never' if a_cf is None else str(a_cf)[:7]})",
                   f"alarm by {str(last)[:7]}, none in cf",
                   f"k={DETECTORS['case_study_comparator']['k']}, h={DETECTORS['case_study_comparator']['h']},"
                   f" mu = mean(t-15..t-4), monitored {str(first)[:7]}..{str(last)[:7]}; cf max S"
                   f" {max(p[3] for p in p_cf):.2f}; ground-truth alarm range {lo}..{hi}"
                   f" {'(inside)' if a_raw and lo <= alarm <= hi else '(outside)'}",
                   raw_path=p_raw, cf_path=p_cf)]


# ---------------------------------------------------------------- distributor churn

def monthly_units(db, s, dist, kind):
    if kind == "secondary":
        sql = f"select date_trunc('month', sale_date)::date, sum(qty) from {dedup(s)} x where distributor_id = %(d)s group by 1"
    else:
        sql = (f"select date_trunc('month', i.invoice_date)::date, sum(l.qty) from {s}.primary_invoices i"
               f" join {s}.primary_invoice_lines l using (invoice_id) where i.distributor_id = %(d)s group by 1")
    return dict(rows(db, sql, d=dist))


def check_c1(db):
    sel = CHURN["selection"]
    q = rows(db, """select distributor_id from raw.distributors where tier = %(t)s and state = %(st)s
                    and district = %(di)s and pincode like %(pp)s and onboarding_date < %(ob)s order by 1""",
             t=str(sel["tier"]), st=sel["state"], di=sel["district"], pp=sel["pincode_prefix"] + "%",
             ob=sel["onboarded_before"])
    qual = [r[0] for r in q]
    dist = CHURN["distributor_id"]
    # base_demand is master data and not in raw; the pre-window year of secondary units is the observable proxy
    vol = dict(rows(db, f"""select distributor_id, sum(qty) from {dedup('raw_cf_distributor_churn')} x
                            where distributor_id = any(%(q)s) and sale_date between %(f)s::date - 365
                            and %(f)s::date - 1 group by 1""", q=qual, f=CHURN["window"]["start"]))
    ranked = sorted(qual, key=lambda d: (vol.get(d, 0), d))
    rank = ranked.index(dist) + 1 if dist in ranked else None
    return [result("C1", dist in qual and len(qual) >= sel["min_qualifying_accounts"],
                   f"{dist} qualifies; {len(qual)} qualify", f">= {sel['min_qualifying_accounts']} qualify, id among them",
                   f"Tier {sel['tier']}, {sel['district']}, {sel['pincode_prefix']}xx, onboarded < {sel['onboarded_before']}:"
                   f" {qual}; pick rule (median base_demand) not observable in raw - proxy rank by pre-window"
                   f" secondary units {rank}/{len(qual)} ({', '.join(f'{d} {vol.get(d, 0)}' for d in ranked)})",
                   qualifying=qual, proxy_rank=rank, proxy_units=vol)]


def check_c2_c6(db):
    dist = CHURN["distributor_id"]
    out = []
    sec = {s: monthly_units(db, s, dist, "secondary") for s in ("raw", "raw_cf_distributor_churn")}
    pri = {s: monthly_units(db, s, dist, "primary") for s in ("raw", "raw_cf_distributor_churn")}
    mult = CHURN["secondary_multiplier"]["by_month"]
    ratios = {m: ratio(sec["raw"].get(date.fromisoformat(m + "-01"), 0),
                       sec["raw_cf_distributor_churn"].get(date.fromisoformat(m + "-01"), 0)) for m in mult}
    feb = ratios["2026-02"]
    lo, hi = CHURN["expected"]["secondary_vs_counterfactual_feb_2026"]
    off = {m: round(r - mult[m], 3) for m, r in ratios.items() if r is None or abs(r - mult[m]) > 0.05}
    hold = [ratio(sec["raw"].get(date(2026, k, 1), 0), sec["raw_cf_distributor_churn"].get(date(2026, k, 1), 0))
            for k in range(3, 9)]
    out.append(result("C2", within(feb, lo, hi) and not off, f"Feb {fmt(feb)}", f"[{lo}, {hi}]; Oct-Feb multipliers +-0.05",
                      "secondary units raw/cf by sale month: " + ", ".join(f"{m} {fmt(r)} (x{mult[m]})" for m, r in ratios.items())
                      + f"; Mar-Aug 2026 hold {', '.join(fmt(r, 2) for r in hold)} (x0.55)"
                      + (f"; off by > 0.05: {off}" if off else ""),
                      ratios=ratios, hold=hold, **{k: {str(m): u for m, u in sorted(v.items())} for k, v in sec.items()}))
    pr = {m: ratio(pri["raw"].get(date(2025, m, 1), 0), pri["raw_cf_distributor_churn"].get(date(2025, m, 1), 0))
          for m in (10, 11, 12)}
    out.append(result("C3", all(within(r, 0.99, 1.01) for r in pr.values()),
                      ", ".join(f"{m}: {fmt(r)}" for m, r in pr.items()), "each [0.99, 1.01]",
                      "primary units raw/cf by invoice month 2025-10..12: "
                      + ", ".join(f"{pri['raw'].get(date(2025, m, 1), 0)}/{pri['raw_cf_distributor_churn'].get(date(2025, m, 1), 0)}"
                                  for m in (10, 11, 12)), ratios=pr))
    jf = [sum(pri[s].get(date(2026, m, 1), 0) for m in (1, 2)) for s in ("raw", "raw_cf_distributor_churn")]
    r_jf = ratio(*jf)
    mar = ratio(pri["raw"].get(date(2026, 3, 1), 0), pri["raw_cf_distributor_churn"].get(date(2026, 3, 1), 0))
    out.append(result("C4", r_jf is not None and r_jf <= 0.35, f"{fmt(r_jf)}", "<= 0.35",
                      f"Jan+Feb 2026 primary units raw {jf[0]} vs cf {jf[1]}; Mar 2026 ratio {fmt(mar, 2)}",
                      raw=jf[0], cf=jf[1], march_ratio=mar))
    late = one(db, """
        with p as (select i.invoice_id, i.due_date, max(c.payment_date) last_pay from raw.primary_invoices i
                   left join raw.collections c using (invoice_id) where i.distributor_id = %(d)s group by 1, 2)
        select percentile_cont(0.5) within group (order by last_pay - due_date)
                   filter (where due_date between '2026-01-01' and '2026-02-28'),
               count(*) filter (where due_date between '2026-01-01' and '2026-02-28'),
               count(*) filter (where due_date between '2026-01-01' and '2026-02-28' and last_pay is null),
               percentile_cont(0.5) within group (order by last_pay - due_date) filter (where extract(year from due_date) = 2025),
               count(*) filter (where extract(year from due_date) = 2025),
               array_agg(last_pay - due_date order by due_date) filter (where due_date between '2026-01-01' and '2026-02-28'),
               count(*) filter (where extract(year from due_date) = 2025 and last_pay - due_date > 14)
        from p""", d=dist)
    med, n, unpaid, med25, n25, days, late25 = late
    out.append(result("C5", within(med, 28, 42) and unpaid == 0 and med25 is not None and med25 <= 5,
                      f"{fmt(med, 1)} d (2025: {fmt(med25, 1)} d)", "[28, 42]; 2025 <= 5",
                      f"last payment - due date, median over {n} invoices due 2026-01-01..02-28 ({unpaid} unpaid)"
                      f" (days late {days}) and {n25} due in 2025 ({late25} of them > 14 d late)",
                      median=med, median_2025=med25, invoices=n, unpaid=unpaid))
    tagged, status = one(db, """select (select count(*) from raw.primary_invoices where distributor_id = %(d)s
                                and scheme_id is not null), (select status from raw.distributors where distributor_id = %(d)s)""",
                         d=dist)
    out.append(result("C6", tagged == 0 and status == "active", f"{tagged} tagged, status {status}", "0, active",
                      f"scheme_id on {dist}'s invoices; distributors.status", tagged=tagged, status=status))
    return out


# ---------------------------------------------------------------- quarter-end stuffing

def window_units(db, s, start, end):
    return {(d, c): u for d, c, u in rows(db, f"""
        select i.distributor_id, p.category, sum(l.qty) from {s}.primary_invoices i
        join {s}.primary_invoice_lines l using (invoice_id) join {s}.products p using (sku)
        where i.invoice_date between %(a)s and %(b)s and p.category in ('tank', 'pipe') group by 1, 2""", a=start, b=end)}


def active_distributors(db, start):
    """Onboarded by the window start and trading: >= 1 primary invoice in [start-90, start-1]."""
    return one(db, """select count(distinct d.distributor_id) from raw.distributors d
                      join raw.primary_invoices i using (distributor_id)
                      where d.onboarding_date <= %(s)s and i.invoice_date between %(s)s::date - 90 and %(s)s::date - 1""",
               s=start)[0]


def stuffing_cells(db):
    """Per cycle, every (distributor, category) with window units in either run: (raw window, stuffing-off window,
    raw trailing-90), the brief's stuffer rule (raw >= 1.8x off), the planted signature used only as a diagnostic
    (raw != off and window/trailing-90 daily rate inside the k band), and the in-window slab invoices."""
    out = {}
    for cyc in STUFF["cycles"]:
        start, end = cyc["start"], cyc["end"]
        days = (end - start).days + 1
        raw, cf = window_units(db, "raw", start, end), window_units(db, "raw_cf_quarter_end_stuffing", start, end)
        base = window_units(db, "raw", start - timedelta(90), start - timedelta(1))
        cells = {k: (raw.get(k, 0), cf.get(k, 0), base.get(k, 0)) for k in raw.keys() | cf.keys()}
        rate = {k: (r / days) / (b / 90) for k, (r, _, b) in cells.items() if b}
        inv = rows(db, """
            select i.invoice_id, i.distributor_id, sc.applies_to_category, sc.min_slab_units, sc.name, d.tier,
                   sum(l.qty) filter (where p.category = sc.applies_to_category)
            from raw.primary_invoices i join raw.schemes sc using (scheme_id) join raw.distributors d using (distributor_id)
            join raw.primary_invoice_lines l using (invoice_id) join raw.products p using (sku)
            where i.invoice_date between %(a)s and %(b)s group by 1, 2, 3, 4, 5, 6""", a=start, b=end)
        out[cyc["fq"]] = {
            "cells": cells, "rate": rate, "invoices": inv,
            "flagged": {k for k, (r, f, _) in cells.items() if r > 0 and r >= 1.8 * f},
            "signature": {k for k, (r, f, _) in cells.items() if r != f and 2.25 <= rate.get(k, 0) <= 2.75},
            "slab": {(d, c) for _, d, c, slab, _, _, u in inv if u and u >= slab},
            "perturbed": sum(r != f for r, f, _ in cells.values()),
        }
    return out


def settled():
    months = set(STUFF["expected"]["settled_cycles_at_as_of"])
    return [c for c in STUFF["cycles"] if c["m"] in months]


def check_s1(db):
    got = {(a, b): (n, cats, disc) for a, b, n, cats, disc in rows(db, """
        select start_date, end_date, count(*), array_agg(name), array_agg(distinct discount_pct)
        from raw.schemes group by 1, 2 order by 1""")}
    problems = []
    for c in STUFF["cycles"]:
        key = (c["start"], c["end"])
        names = sorted(STUFF["schemes"]["name_pattern"].format(fq=c["fq"], Category=cat.title(), tier=t)
                       for cat in STUFF["schemes"]["per_window"]["categories"] for t in STUFF["schemes"]["per_window"]["tiers"])
        disc = STUFF["schemes"]["discount_pct"]["fiscal_year_end" if c.get("fy_end") else "default"]
        if key not in got:
            problems.append(f"{c['fq']} missing")
        elif got[key][0] != 6 or sorted(got[key][1]) != names or [float(x) for x in got[key][2]] != [disc]:
            problems.append(f"{c['fq']} {got[key][0]} rows {got[key][2]}")
    extra = [k for k in got if k not in {(c["start"], c["end"]) for c in STUFF["cycles"]}]
    early = one(db, "select count(*), count(*) filter (where start_date between '2023-12-01' and '2023-12-31')"
                    " from raw.schemes where start_date < '2024-03-17'")
    n_cf = one(db, "select count(*) from raw_cf_quarter_end_stuffing.schemes")[0]
    ok = not problems and not extra and early == (0, 0)
    return [result("S1", ok, f"{len(got)} windows x {sorted({v[0] for v in got.values()})} rows", "11 windows x 6; none before 2024-03-17",
                   f"windows match ground truth (names, 0.03/0.04 discounts); {early[0]} before 2024-03-17, {early[1]} in Dec 2023;"
                   f" {len(extra)} unexpected windows; stuffing-off schema has {n_cf} scheme rows"
                   + (f"; problems: {problems}" if problems else ""), problems=problems, extra=[str(e) for e in extra])]


def check_s2_s6(db, cells):
    fqs = [c["fq"] for c in settled()]
    per, out = {}, []
    for cyc in STUFF["cycles"]:
        fq, x = cyc["fq"], cells[cyc["fq"]]
        dists = {d for d, _ in x["flagged"]}
        slab_d = {d for d, _ in x["slab"]}
        n_active = active_distributors(db, cyc["start"])
        planted = {d for d, c in x["signature"] & x["slab"]}
        inv = x["invoices"]
        untagged = one(db, """
            select count(*) from (select i.invoice_id from raw.primary_invoices i join raw.distributors d using (distributor_id)
                join raw.primary_invoice_lines l using (invoice_id) join raw.products p using (sku)
                join raw.schemes sc on sc.applies_to_category = p.category and sc.start_date = %(a)s
                     and sc.name like '%%- Tier ' || d.tier
                where i.invoice_date between %(a)s and %(b)s and i.scheme_id is null
                group by i.invoice_id, sc.scheme_id, sc.min_slab_units having sum(l.qty) >= sc.min_slab_units) x""",
                       a=cyc["start"], b=cyc["end"])[0]
        per[fq] = {
            "stuffers": len(dists), "cells": len(x["flagged"]), "active": n_active, "share": len(dists) / n_active,
            "rate_mean": statistics.mean(x["rate"].get(k, 0) for k in x["flagged"]),
            "rate_min": min(x["rate"].get(k, 0) for k in x["flagged"]),
            "rate_mean_flagged_with_slab": statistics.mean(x["rate"].get(k, 0) for k in x["flagged"] & x["slab"]),
            "no_slab_invoice": sorted(dists - slab_d),
            "no_slab_invoice_outside_k_band": sum(1 for d in dists - slab_d
                                                  if not any((d, c) in x["signature"] for c in ("tank", "pipe"))),
            "signature_cells_missed_by_rule": len(x["signature"] - x["flagged"]),
            "flagged_cells_outside_k_band": len(x["flagged"] - x["signature"]),
            "planted_signature_share": len(planted) / n_active,
            "perturbed_cells": x["perturbed"],
            "non_stuffer_tagged_invoices": sum(1 for r in inv if r[1] not in dists),
            "non_stuffer_tagged_distributors": len({r[1] for r in inv if r[1] not in dists}),
            "stuffer_tagged_invoices": sum(1 for r in inv if r[1] in dists),
            "tagged_below_slab": sum(1 for r in inv if not r[6] or r[6] < r[3]),
            "tagged_wrong_tier": sum(1 for r in inv if not r[4].endswith(f"Tier {r[5]}")),
            "untagged_at_slab": untagged,
        }
    s = {f: per[f] for f in fqs}
    bad = {f: round(v["share"], 3) for f, v in s.items() if not within(v["share"], 0.15, 0.20)}
    sig = [v["planted_signature_share"] for v in s.values()]
    out.append(result("S2", not bad, f"{min(v['share'] for v in s.values()):.1%}-{max(v['share'] for v in s.values()):.1%}",
                      "each settled cycle [15%, 20%]",
                      "stuffers (window units >= 1.8x stuffing-off run, tank or pipe) / active (onboarded, invoiced in"
                      " trailing 90 d): " + ", ".join(f"{f} {v['stuffers']}/{v['active']}" for f, v in s.items())
                      + (f"; outside: {bad}" if bad else "")
                      + f"; rule diagnostic: it misses {sum(v['signature_cells_missed_by_rule'] for v in s.values())} cells"
                      f" with the planted signature (raw != off, window/trailing-90 in [2.25, 2.75]) and admits"
                      f" {sum(v['flagged_cells_outside_k_band'] for v in s.values())} outside it; signature + slab-invoice"
                      f" share {min(sig):.1%}-{max(sig):.1%}", per_cycle=per))
    lo, hi = STUFF["expected"]["window_rate_vs_trailing90_stuffer_mean"]
    bad = {f: round(v["rate_mean"], 3) for f, v in s.items() if not within(v["rate_mean"], lo, hi)}
    alt = [v["rate_mean_flagged_with_slab"] for v in s.values()]
    out.append(result("S3", not bad,
                      f"{min(v['rate_mean'] for v in s.values()):.2f}-{max(v['rate_mean'] for v in s.values()):.2f}",
                      f"each settled cycle [{lo}, {hi}]",
                      "mean over rule-stuffer cells of window daily / own [start-90, start-1] daily units: "
                      + ", ".join(f"{f} {v['rate_mean']:.2f} (min {v['rate_min']:.2f})" for f, v in s.items())
                      + (f"; outside: {bad}" if bad else "")
                      + f"; restricted to cells with a slab invoice in the category: {min(alt):.2f}-{max(alt):.2f}"))
    missing = [f"{f}:{d}" for f, v in s.items() for d in v["no_slab_invoice"]]
    off_band = sum(v["no_slab_invoice_outside_k_band"] for v in s.values())
    rule = {f: {k: v[k] for k in ("tagged_below_slab", "tagged_wrong_tier", "untagged_at_slab") if v[k]}
            for f, v in per.items()}
    rule = {f: v for f, v in rule.items() if v}
    out.append(result("S4", not missing,
                      f"{len(missing)} of {sum(v['stuffers'] for v in s.values())} without a slab invoice", "0",
                      "in-window scheme_id invoice with category units >= min_slab_units, settled cycles;"
                      + (f" missing {missing[:8]}{' ...' if len(missing) > 8 else ''} ({off_band} of them have no cell"
                         " in the planted k band);" if missing else "")
                      + (f" tagging-rule exceptions {rule}" if rule else " tagging rule (D9) holds in every window"),
                      missing=missing))
    ns = sum(v["non_stuffer_tagged_invoices"] for v in s.values())
    out.append(result("S6", ns > 0, f"{ns} non-stuffer tagged invoices", "> 0",
                      "scheme-tagged in-window invoices of non-stuffers, settled cycles (distributors / vs stuffer"
                      " invoices): " + ", ".join(f"{f} {v['non_stuffer_tagged_invoices']}"
                                                 f" ({v['non_stuffer_tagged_distributors']} / {v['stuffer_tagged_invoices']})"
                                                 for f, v in s.items())))
    return out


def build_ledger(db, s):
    """Temp table ledger_<s>: daily (distributor, category) channel stock and trailing-30 average daily
    de-duplicated secondary, for the two scheme categories."""
    db.execute(f"""
        create temp table if not exists ledger_{s} as
        with f as (
            select o.distributor_id d, p.category c, o.as_of_date dt, sum(o.qty) q, 0::bigint sq
            from {s}.opening_channel_stock o join {s}.products p using (sku) where p.category in ('tank', 'pipe')
            group by 1, 2, 3
            union all
            select i.distributor_id, p.category, i.invoice_date, sum(l.qty), 0 from {s}.primary_invoice_lines l
            join {s}.primary_invoices i using (invoice_id) join {s}.products p using (sku)
            where p.category in ('tank', 'pipe') group by 1, 2, 3
            union all
            select x.distributor_id, p.category, x.sale_date, -sum(x.qty), sum(x.qty) from {dedup(s)} x
            join {s}.products p using (sku) where p.category in ('tank', 'pipe') group by 1, 2, 3),
        g as (select d, c, dt, sum(q) q, sum(sq) sq from f group by 1, 2, 3),
        grid as materialized (select d, c, gs::date dt from (select distinct d, c from g) k,
                 generate_series(%(w)s::date, %(a)s::date, interval '1 day') gs)
        select grid.d, grid.c, grid.dt, sum(coalesce(g.q, 0)) over w stock,
               sum(coalesce(g.sq, 0)) over (w rows between 29 preceding and current row) / 30.0 trail
        from grid left join g using (d, c, dt) window w as (partition by grid.d, grid.c order by grid.dt)""",
               {"w": WINDOW_START, "a": AS_OF})
    db.execute(f"create index if not exists ledger_{s}_key on ledger_{s} (d, c, dt)")
    db.execute(f"analyze ledger_{s}")


def excess_dos(db, cohort, s):
    """Per settled cycle, for the cohort's (distributor, category) cells in schema s: min / max over QE+1..QE+60 and
    the next-start value of the cohort mean of (days of stock - own [start-90, start-1] median), plus the cohort's
    aggregate days of stock (sum stock / sum trailing daily secondary) at QE+1 and at the next start."""
    cycles = STUFF["cycles"]
    nxt = {c["fq"]: (cycles[i + 1]["start"] if i + 1 < len(cycles) else STUFF["live_tail_next_starts"][0])
           for i, c in enumerate(cycles)}
    db.execute("create temp table if not exists cohort (fq text, ws date, qe date, nxt date, d text, c text)")
    db.execute("truncate cohort")
    with db.cursor() as cur:
        cur.executemany("insert into cohort values (%s, %s, %s, %s, %s, %s)",
                        [(c["fq"], c["start"], c["end"], nxt[c["fq"]], d, cat)
                         for c in settled() for d, cat in cohort[c["fq"]]])
    res = rows(db, f"""
        with x as (select h.fq, h.ws, h.qe, h.nxt, h.d, h.c, l.dt, l.stock, l.trail, l.stock / l.trail dos
                   from cohort h join ledger_{s} l on l.d = h.d and l.c = h.c and l.dt between h.ws - 90 and h.nxt
                   where l.trail > 0),
        m as (select fq, d, c, percentile_cont(0.5) within group (order by dos) med from x
              where dt between ws - 90 and ws - 1 group by 1, 2, 3),
        e as (select x.fq, x.qe, x.nxt, x.dt, avg(x.dos - m.med) ex, sum(x.stock) / sum(x.trail) agg
              from x join m using (fq, d, c) group by 1, 2, 3, 4)
        select fq, min(ex) filter (where dt between qe + 1 and qe + 60), max(ex) filter (where dt between qe + 1 and qe + 60),
               max(ex) filter (where dt = nxt), max(agg) filter (where dt = qe + 1), max(agg) filter (where dt = nxt)
        from e group by fq order by min(qe)""")
    return {fq: {"min_excess_qe1_qe60": lo, "max_excess_qe1_qe60": hi, "excess_at_next_start": at,
                 "cohort_dos_qe1": float(q1), "cohort_dos_next_start": float(qn)}
            for fq, lo, hi, at, q1, qn in res}


def check_s5(db, cells):
    cohort = {fq: x["flagged"] for fq, x in cells.items()}
    for s in ("raw", "raw_cf_quarter_end_stuffing"):
        build_ledger(db, s)
    per = excess_dos(db, cohort, "raw")
    off = excess_dos(db, cohort, "raw_cf_quarter_end_stuffing")
    target = STUFF["expected"]["stuffer_cohort_mean_excess_dos_through_qe_plus_60_min"]
    bad = [fq for fq, v in per.items() if not (v["min_excess_qe1_qe60"] >= target and v["excess_at_next_start"] <= 1)]
    for fq, v in per.items():
        v["stuffing_off"] = off[fq]
    return [result("S5", not bad and len(per) == len(settled()),
                   f"min {min(v['min_excess_qe1_qe60'] for v in per.values()):.1f} d; next start max"
                   f" {max(v['excess_at_next_start'] for v in per.values()):.1f} d",
                   f">= +{target} d QE+1..QE+60; <= +1 d at next start",
                   "stuffer cohort mean of (category stock / trailing-30 daily de-duplicated secondary) - own"
                   " [start-90, start-1] median, min over QE+1..QE+60 / at next start: "
                   + ", ".join(f"{fq} {v['min_excess_qe1_qe60']:.1f}/{v['excess_at_next_start']:.1f}" for fq, v in per.items())
                   + (f"; failing: {bad}" if bad else "")
                   + "; same cohort's aggregate days of stock at QE+1 and next start, raw vs stuffing-off run: "
                   + ", ".join(f"{fq} {v['cohort_dos_qe1']:.0f}/{v['cohort_dos_next_start']:.0f} vs"
                               f" {off[fq]['cohort_dos_qe1']:.0f}/{off[fq]['cohort_dos_next_start']:.0f}"
                               for fq, v in per.items()), per_cycle=per)]


# ---------------------------------------------------------------- installer decoy

def installer_rate(db, s, ins, district, horizon, own):
    return one(db, f"""
        with u as (select i.serial, i.install_date from {s}.installations i join {s}.installers r using (installer_id)
                   where r.district = %(di)s and (i.installer_id = %(ins)s) = %(own)s
                   and i.install_date <= %(a)s::date - %(h)s)
        select (select count(*) from u), (select count(*) from u join {s}.warranty_claims c using (serial)
                                          where c.claim_date < u.install_date + %(h)s)""",
               di=district, ins=ins, own=own, a=AS_OF, h=horizon)


def check_i1(db):
    ins = DECOY["installer_id"]
    district, state = one(db, """select r.district, (select min(state) from raw.geo_pincodes g where g.district = r.district)
                                 from raw.installers r where installer_id = %(i)s""", i=ins)
    first, others, per_month, share, off_district = one(db, """
        with a as (select i.installer_id, i.install_date, g.district pin_district from raw.installations i
                   join raw.installers r using (installer_id) left join raw.geo_pincodes g using (pincode)
                   where r.district = %(di)s)
        select (select min(install_date) from a where installer_id = %(i)s),
               (select count(distinct installer_id) from a where installer_id <> %(i)s and install_date >= %(f)s),
               (select count(*) / count(distinct date_trunc('month', install_date))::float from a
                where installer_id = %(i)s and install_date < date_trunc('month', %(asof)s::date)),
               (select avg((installer_id = %(i)s)::int) from a where install_date >= %(f)s),
               (select count(*) from a where installer_id = %(i)s and pin_district is distinct from %(di)s)""",
                                                       i=ins, di=district, f=DECOY["first_install_date"], asof=AS_OF)
    exp = DECOY["volume"]
    ok = (district == DECOY["district"] and state == DECOY["state"] and others >= DECOY["district_min_other_active_installers"]
          and first >= DECOY["first_install_date"])
    return [result("I1", ok, f"{per_month:.1f}/month, {share:.1%} of district", f"about {exp['expected_per_month']}/mo,"
                   f" {exp['installer_registered_share_of_district']:.0%}; >= 6 peers; first >= {DECOY['first_install_date']}",
                   f"{ins} in {district}, {state}; first attributed install {first}; {others} other installers active"
                   f" since {DECOY['first_install_date']}; {off_district} of its installs outside the district's pincodes",
                   district=district, state=state, first_install=str(first), other_active=others,
                   per_month=per_month, share=share)]


def check_i2(db):
    ins, district = DECOY["installer_id"], DECOY["district"]
    detail, ev = {}, []
    for s in ("raw", "raw_cf_installer_decoy"):
        for h in (180, 365):
            n1, a = installer_rate(db, s, ins, district, h, True)
            n2, b = installer_rate(db, s, ins, district, h, False)
            rr, lo, hi = rate_ratio_ci(a, n1, b, n2)
            detail[f"{s}.{h}"] = {"units": n1, "claims": a, "loo_units": n2, "loo_claims": b, "ratio": rr, "ci95": [lo, hi]}
            ev.append(f"{s} {h} d: {a}/{n1} vs {b}/{n2} = {fmt(rr, 2)} ({fmt(lo, 2)}-{fmt(hi, 2)})")
    own = {h: ratio(detail[f"raw.{h}"]["claims"], detail[f"raw_cf_installer_decoy.{h}"]["claims"]) for h in (180, 365)}
    ev.append("installer's own claims raw / decoy-off run (same units): "
              + ", ".join(f"{h} d {fmt(r, 2)}x" for h, r in own.items()))
    lo, hi = DECOY["expected"]["claim_rate_vs_leave_one_out"]
    raw_r = [detail[f"raw.{h}"]["ratio"] for h in (180, 365)]
    cf_r = [detail[f"raw_cf_installer_decoy.{h}"]["ratio"] for h in (180, 365)]
    ok = all(within(r, lo, hi) for r in raw_r) and all(within(r, 0.6, 1.6) for r in cf_r)
    return [result("I2", ok, f"{fmt(raw_r[0], 2)}x / {fmt(raw_r[1], 2)}x (cf {fmt(cf_r[0], 2)} / {fmt(cf_r[1], 2)})",
                   f"[{lo}, {hi}] at 180 and 365 d; cf [0.6, 1.6]",
                   "claims per unit, installer vs same-district other installers, install clock: " + "; ".join(ev), **detail)]


def check_i3_i4(db):
    ins = DECOY["installer_id"]
    mix = rows(db, """select b.plant_id, b.line_no, b.resin_lot_id, count(*) from raw.installations i
                      join raw.serial_units su using (serial) join raw.production_batches b using (batch_id)
                      where i.installer_id = %(i)s group by 1, 2, 3""", i=ins)
    total = sum(r[3] for r in mix)
    plants = {}
    for p, _, _, n in mix:
        plants[p] = plants.get(p, 0) + n
    shares = {p: n / total for p, n in plants.items()}
    lots = {r[2] for r in mix}
    l2 = sum(n for p, line, _, n in mix if p == "DGP" and line == 2)
    sup = DECOY["supply"]
    big = [p for p, sh in shares.items() if sh >= sup["min_share_each_plant"]]
    out = [result("I3", len(big) >= 2 and len(lots) >= sup["min_distinct_resin_lots"] and l2 == 0,
                  f"{len(big)} plants >= 20%, {len(lots)} lots, {l2} DGP-L2", ">= 2 plants >= 20%, >= 5 lots, 0 DGP-L2",
                  f"{total:,} attributed units by plant: " + ", ".join(f"{p} {sh:.1%}" for p, sh in sorted(shares.items())),
                  plant_shares=shares, resin_lots=len(lots), dgp_l2_units=l2)]
    b = one(db, """
        with k as (select su.batch_id, b.resin_lot_id from raw.installations i join raw.serial_units su using (serial)
                   join raw.production_batches b using (batch_id) where i.installer_id = %(i)s),
        bs as (select batch_id, count(*) n from raw.serial_units group by 1),
        bk as (select batch_id, count(*) x from k group by 1),
        ls as (select b.resin_lot_id, count(*) n from raw.serial_units su join raw.production_batches b using (batch_id) group by 1),
        lk as (select resin_lot_id, count(*) x from k group by 1)
        select count(*) filter (where n >= 100), max(x::float / n) filter (where n >= 100),
               count(*) filter (where n >= 20), count(x) filter (where n >= 20), max(x::float / n) filter (where n >= 20),
               count(*) filter (where n >= 20 and x::float / n > %(cap)s),
               max(n), (select max(x::float / n) from ls join lk using (resin_lot_id)),
               (select count(*) from lk), (select max(x) from bk)
        from bs left join bk using (batch_id)""", i=ins, cap=DECOY["expected"]["max_share_of_any_batch_or_lot"])
    n100, s100, n20, n20_hit, s20, n20_over, max_n, s_lot, n_lot, max_x = b
    cap = DECOY["expected"]["max_share_of_any_batch_or_lot"]
    out.append(result("I4", (s100 or 0) <= cap and s_lot <= cap,
                      f"batches>=100: {n100} exist (max share {fmt(s100)}); lots max {s_lot:.3%}",
                      f"<= {cap:.0%} of every batch >= 100 units and every lot",
                      f"no batch reaches 100 units (largest {max_n}), so the batch clause is vacuous as written;"
                      f" over the {n20:,} batches with >= 20 units (installer in {n20_hit:,}) its max share is"
                      f" {s20:.1%} (most units in one batch: {max_x}) and it exceeds {cap:.0%} in {n20_over} of them;"
                      f" max share over its {n_lot} resin lots {s_lot:.3%}",
                      batches_ge_100=n100, max_share_ge_100=s100, batches_ge_20=n20, max_share_ge_20=s20,
                      batches_ge_20_over_cap=n20_over, largest_batch=max_n, max_share_lot=s_lot, lots=n_lot))
    return out


# ---------------------------------------------------------------- main

def run_checks(db, only):
    cache = {}

    def cells():
        if not cache:
            cache["v"] = stuffing_cells(db)
        return cache["v"]

    plan = [
        ("G1", lambda: check_g1(db)), ("G2", lambda: check_g2(db)), ("G3", lambda: check_g3(db)),
        ("G4", lambda: check_g4(db)), ("G5", lambda: check_g5(db)), ("G6", lambda: check_g6(db)),
        ("G7", lambda: check_g7(db)),
        ("R1", lambda: check_r1(db)), ("R2", lambda: check_r2_r3(db)), ("R4", lambda: check_r4(db)),
        ("R5", lambda: check_r5(db)), ("R6", lambda: check_r6(db)),
        ("R7", lambda: [deferred("R7", "lot scan flags the lot by 2025-09-28; only / top flagged lot",
                                 "needs the pre-registered lot_scan detector (not built yet)")]),
        ("C1", lambda: check_c1(db)), ("C2", lambda: check_c2_c6(db)),
        ("C7", lambda: [deferred("C7", "health score crosses by 2026-01-31; < 5% of stuffers cross",
                                 "needs distributor_health_score (not built yet)")]),
        ("S1", lambda: check_s1(db)), ("S2", lambda: check_s2_s6(db, cells())), ("S5", lambda: check_s5(db, cells())),
        ("I1", lambda: check_i1(db)), ("I2", lambda: check_i2(db)), ("I3", lambda: check_i3_i4(db)),
        ("I5", lambda: [deferred("I5", "installer scan flags it; no batch/lot outside the resin lot flagged",
                                 "needs installer_scan and lot_scan detectors (not built yet)")]),
    ]
    results, timings = [], {}
    for key, fn in plan:
        if only and key not in only:
            continue
        t0 = time.perf_counter()
        try:
            got = fn()
        except (psycopg.Error, ArithmeticError, LookupError, TypeError, ValueError) as exc:  # crash = FAIL
            db.rollback()
            got = [result(key, False, "error", "-", f"{type(exc).__name__}: {exc}".replace("\n", " "))]
        timings[key] = round(time.perf_counter() - t0, 2)
        for r in got:
            r["seconds"] = timings[key]
        results += got
        for r in got:
            print(f"  {r['id']:<4} {r['status']:<8} {r['measured']}", flush=True)
    return sorted(results, key=lambda r: ("GRCSI".index(r["id"][0]), r["id"])), timings


def print_table(results):
    print(f"\n{'id':<5}{'status':<10}{'measured':<44}{'target':<40}evidence")
    for r in results:
        print(f"{r['id']:<5}{r['status']:<10}{str(r['measured'])[:43]:<44}{str(r['target'])[:39]:<40}{r['evidence']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--regenerate", action="store_true", help="rebuild the comparison schemas even if they exist")
    ap.add_argument("--checks", default="", help="comma-separated check groups to run, e.g. G1,R2 (default: all)")
    args = ap.parse_args()
    t0 = time.perf_counter()
    with psycopg.connect(**PG, autocommit=True) as db:
        gen = ensure_schemas(db, args.regenerate)
        t_gen = time.perf_counter() - t0
        results, timings = run_checks(db, {c.strip() for c in args.checks.split(",") if c.strip()})
        counts = {s: sum(one(db, f"select count(*) from {s}.{t}")[0] for t in raw_tables(db, s)) for s in SCHEMAS}
    for s, n in counts.items():
        gen[s]["total_rows"] = n
    print_table(results)
    failed = [r["id"] for r in results if r["status"] == "FAIL"]
    total = time.perf_counter() - t0
    summary = {"pass": sum(r["status"] == "PASS" for r in results), "fail": len(failed),
               "deferred": sum(r["status"] == "DEFERRED" for r in results), "failed_ids": failed}
    report = {"as_of": gen["raw"]["as_of"], "seed": gen["raw"]["seed"], "anchor": gen["raw"]["anchor"],
              "ground_truth_version": GT["version"], "summary": summary, "schemas": gen,
              "row_counts": next((r["detail"]["per_table"] for r in results if r["id"] == "G1"), None),
              "timings_seconds": {"total": round(total, 1), "generation": round(t_gen, 1), "checks": timings},
              "checks": results}
    REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\n{summary['pass']} PASS, {summary['fail']} FAIL, {summary['deferred']} DEFERRED in {total:.0f} s"
          f" (generation {t_gen:.0f} s); report: {REPORT}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
