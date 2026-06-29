"""CARE_SITE 도메인.

원본: ``care_site/step02_careSite.sas``.
provider 엑셀(care_site_id, care_site_rawname, concept_id)을 care_site_id 로
묶어 이름은 ``', '`` 로 연결, 첫 concept_id 를 place_of_service_concept_id 로 둔다.
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
        "care_site_name": grp["care_site_rawname"].apply(
            lambda s: ", ".join(s.dropna().astype(str))
        ).values,
        "place_of_service_concept_id": grp["concept_id"].first().fillna(0).astype("int64").values,
    })
    out["location_id"] = pd.NA
    out["care_site_source_value"] = ""
    out["place_of_service_source_value"] = ""
    return select_columns(out, "care_site")
