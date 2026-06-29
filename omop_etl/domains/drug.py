"""DRUG_EXPOSURE 도메인.

condition 과 거의 동일하나 ① quantity = quantity_days * days_supply 계산,
② 2단계 매칭 2차에서 9203 NULL 처리, ③ drug_concept_id 는 원천 conceptid 사용.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..cdm_schema import select_columns
from ..config import PipelineConfig
from ..ids import assign_occurrence_id, filter_person_id_length
from ..person_filter import (
    apply_cutoff,
    exclude_persons,
    keep_in_person_master,
    load_excluded_persons,
    remove_after_death,
    validate_against_person,
)
from ..visit_match import match_visit_two_pass
from ._common import load_sources


def build(
    cfg: PipelineConfig,
    person: pd.DataFrame,
    death: pd.DataFrame,
    visit: pd.DataFrame,
    *,
    person_id_xlsx: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dom = cfg.domains["drug"]
    a = load_sources(dom, cfg)
    a["quantity"] = a["quantity_days"] * a["days_supply"]

    a = match_visit_two_pass(a, visit, date_col="drug_exposure_start_date", **dom.visit_match)
    a = apply_cutoff(a, date_col="drug_exposure_start_date", cutoff_year=dom.cutoff_year)

    a = assign_occurrence_id(
        a,
        id_col="drug_exposure_id",
        datetime_col="drug_exposure_start_datetime",
        date_col="drug_exposure_start_date",
        domain_code=dom.domain_code,
        seq_width=dom.seq_width,
    )
    # 상수 컬럼
    a["dose_unit_concept_id"] = 0
    a["dose_unit_source_value"] = ""
    a["drug_source_concept_id"] = 0
    a["effective_drug_dose"] = ""
    a["lot_number"] = pd.NA
    a["refills"] = ""
    a["route_source_value"] = ""
    a["sig"] = pd.NA
    a["stop_reason"] = ""
    a["verbatim_end_date"] = ""
    a["visit_detail_id"] = a["visit_occurrence_id"]
    if "conceptid" in a.columns:
        a = a.rename(columns={"conceptid": "drug_concept_id"})

    a = remove_after_death(a, death, date_col="drug_exposure_start_date")
    a = filter_person_id_length(a)

    excluded = load_excluded_persons(person_id_xlsx)
    a = exclude_persons(a, excluded)
    invalid = validate_against_person(a, person, date_col="drug_exposure_start_date")
    a = keep_in_person_master(a, person)

    a = a.rename(columns={"PERSON_ID": "person_id"})
    return select_columns(a, "drug_exposure").drop_duplicates(), invalid
