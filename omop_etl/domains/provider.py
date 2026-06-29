"""PROVIDER 도메인.

care_site 와 동일한 provider 엑셀을 쓰되 provider_id = care_site_id 로 두고
specialty_concept_id 에 첫 concept_id 를 둔다.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..cdm_schema import select_columns
from ..io import read_excel


def build(provider_xlsx: str | Path, *, sheet: str | int = 0) -> pd.DataFrame:
    a = read_excel(provider_xlsx, sheet=sheet)
    a = a[["care_site_id", "care_site_rawname", "concept_id"]].drop_duplicates()
    a = a.sort_values("care_site_id")

    grp = a.groupby("care_site_id", sort=True)
    out = pd.DataFrame({
        "care_site_id": list(grp.groups.keys()),
        "provider_name": grp["care_site_rawname"].apply(
            lambda s: ", ".join(s.dropna().astype(str))
        ).values,
        "specialty_concept_id": grp["concept_id"].first().fillna(0).astype("int64").values,
    })
    out["provider_id"] = out["care_site_id"]
    out["npi"] = ""
    out["dea"] = ""
    out["year_of_birth"] = pd.NA
    out["gender_concept_id"] = 0
    out["provider_source_value"] = ""
    out["specialty_source_value"] = ""
    out["specialty_source_concept_id"] = 0
    out["gender_source_value"] = ""
    out["gender_source_concept_id"] = 0
    return select_columns(out, "provider")
