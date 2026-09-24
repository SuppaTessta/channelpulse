import pytest

from app.guardrails.region import ALL_REGIONS, REGIONS, parse_region_claim


@pytest.mark.parametrize("region", REGIONS)
def test_each_sales_region_is_a_valid_claim(region):
    assert parse_region_claim(region) == region


@pytest.mark.parametrize(("header", "expected"), [(None, "ALL"), ("", "ALL"), ("  ", "ALL"), ("all", "ALL"),
                                                  (" bihar & jharkhand ", "Bihar & Jharkhand")])
def test_claims_are_trimmed_case_folded_and_default_to_all(header, expected):
    assert parse_region_claim(header) == expected


@pytest.mark.parametrize("header", ["Kolkata", "West Bengal", "ALL; drop table x", "Assam,Odisha"])
def test_anything_else_is_rejected(header):
    with pytest.raises(ValueError, match="X-Demo-Region must be one of"):
        parse_region_claim(header)


def test_the_claim_reaches_the_database_call(api):
    api.http.get("/api/anomalies", headers={"X-Demo-Region": "north east"})
    assert api.db.calls[-1][2] == "North East"


def test_a_missing_header_is_the_all_regions_demo_user(api):
    api.http.get("/api/anomalies")
    assert api.db.calls[-1][2] == ALL_REGIONS


def test_an_invalid_claim_is_a_400(api):
    response = api.http.get("/api/anomalies", headers={"X-Demo-Region": "Mars"})
    assert response.status_code == 400 and api.db.calls == []
