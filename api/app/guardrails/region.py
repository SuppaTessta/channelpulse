"""Region claim: the Phase-1 RLS stub (PLAN §8). There is no authentication.

The dashboard's demo "viewing as" picker sends X-Demo-Region. The API only checks that it names one of the six sales
regions or ALL, then passes it to Postgres per transaction (set_config('app.region', claim, true), see readonly_db).
The row filtering itself is done by the RLS policies dbt puts on the distributor-level marts. ALL, the default, is the
public demo user and sees every region. A real deployment would take the claim from a verified token instead.
"""

import logging

from fastapi import Header, HTTPException

REGIONS = ("South Bengal", "North Bengal & Sikkim", "Assam", "North East", "Bihar & Jharkhand", "Odisha")
ALL_REGIONS = "ALL"
_CANONICAL = {claim.casefold(): claim for claim in (*REGIONS, ALL_REGIONS)}

log = logging.getLogger("channelpulse.api")


def parse_region_claim(value: str | None) -> str:
    """Canonical claim for a header value (missing or blank means ALL); ValueError if it names no region."""
    if value is None or not value.strip():
        return ALL_REGIONS
    try:
        return _CANONICAL[value.strip().casefold()]
    except KeyError:
        raise ValueError(f"X-Demo-Region must be one of {', '.join((*REGIONS, ALL_REGIONS))}") from None


def region_claim(x_demo_region: str | None = Header(default=None)) -> str:
    """FastAPI dependency: the validated claim for this request, logged."""
    try:
        claim = parse_region_claim(x_demo_region)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    log.info("region claim: %s", claim)
    return claim
