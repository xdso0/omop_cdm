"""OMOP CDM 테이블별 최종 컬럼 정의.

각 CDM 테이블의 표준 컬럼과 순서를 정의한다. :func:`select_columns` 로 최종
산출물의 컬럼 순서를 강제한다.
"""
from __future__ import annotations

import pandas as pd

CDM_COLUMNS: dict[str, list[str]] = {
    "person": [
        "person_id", "gender_concept_id", "year_of_birth", "month_of_birth",
        "day_of_birth", "birth_datetime", "race_concept_id", "ethnicity_concept_id",
        "location_id", "provider_id", "care_site_id", "person_source_value",
        "gender_source_value", "gender_source_concept_id", "race_source_value",
        "race_source_concept_id", "ethnicity_source_value", "ethnicity_source_concept_id",
    ],
    "death": [
        "person_id", "death_date", "death_datetime", "death_type_concept_id",
        "cause_concept_id", "cause_source_value", "cause_source_concept_id",
    ],
    "care_site": [
        "care_site_id", "care_site_name", "place_of_service_concept_id",
        "location_id", "care_site_source_value", "place_of_service_source_value",
    ],
    "provider": [
        "provider_id", "provider_name", "npi", "dea", "specialty_concept_id",
        "care_site_id", "year_of_birth", "gender_concept_id", "provider_source_value",
        "specialty_source_value", "specialty_source_concept_id", "gender_source_value",
        "gender_source_concept_id",
    ],
    "visit_occurrence": [
        "visit_occurrence_id", "person_id", "visit_concept_id", "visit_start_date",
        "visit_start_datetime", "visit_end_date", "visit_end_datetime",
        "visit_type_concept_id", "provider_id", "care_site_id", "visit_source_value",
        "visit_source_concept_id", "admitting_source_concept_id", "admitting_source_value",
        "discharge_to_concept_id", "discharge_to_source_value",
        "preceding_visit_occurrence_id",
    ],
    "payer_plan_period": [
        "payer_plan_period_id", "person_id", "payer_plan_period_start_date",
        "payer_plan_period_end_date", "payer_source_value", "plan_source_value",
        "family_source_value",
    ],
    "visit_cost": [
        "visit_cost_id", "visit_occurrence_id", "currency_concept_id", "paid_copay",
        "paid_coinsurance", "paid_toward_deductible", "paid_by_payer",
        "paid_by_coordination_benefits", "total_out_of_pocket", "total_paid",
        "payer_plan_period_id",
    ],
    "condition_occurrence": [
        "condition_occurrence_id", "person_id", "condition_concept_id",
        "condition_start_date", "condition_start_datetime", "condition_end_date",
        "condition_end_datetime", "condition_type_concept_id",
        "condition_status_concept_id", "stop_reason", "provider_id",
        "visit_occurrence_id", "visit_detail_id", "condition_source_value",
        "condition_source_concept_id", "condition_status_source_value",
    ],
    "drug_exposure": [
        "drug_exposure_id", "person_id", "drug_concept_id", "drug_exposure_start_date",
        "drug_exposure_start_datetime", "drug_exposure_end_date",
        "drug_exposure_end_datetime", "verbatim_end_date", "drug_type_concept_id",
        "stop_reason", "refills", "quantity", "quantity_days", "days_supply", "sig",
        "route_concept_id", "effective_drug_dose", "dose_unit_concept_id",
        "lot_number", "provider_id", "visit_occurrence_id", "visit_detail_id",
        "drug_source_value", "drug_source_concept_id", "route_source_value",
        "dose_unit_source_value",
    ],
    "procedure_occurrence": [
        "procedure_occurrence_id", "person_id", "procedure_concept_id",
        "procedure_date", "procedure_datetime", "procedure_type_concept_id",
        "modifier_concept_id", "quantity", "provider_id", "visit_occurrence_id",
        "visit_detail_id", "procedure_source_value", "procedure_source_concept_id",
        "modifier_source_value",
    ],
    "measurement": [
        "measurement_id", "person_id", "measurement_concept_id", "measurement_date",
        "measurement_datetime", "measurement_type_concept_id", "operator_concept_id",
        "value_as_number", "value_as_concept_id", "unit_concept_id", "range_low",
        "range_high", "provider_id", "visit_occurrence_id", "visit_detail_id",
        "measurement_source_value", "measurement_source_concept_id",
        "unit_source_value", "value_source_value",
    ],
    "observation": [
        "observation_id", "person_id", "observation_concept_id", "observation_date",
        "observation_datetime", "observation_type_concept_id", "value_as_number",
        "value_as_string", "value_as_concept_id", "qualifier_concept_id",
        "unit_concept_id", "provider_id", "visit_occurrence_id", "visit_detail_id",
        "observation_source_value", "observation_source_concept_id",
        "unit_source_value", "qualifier_source_value",
    ],
    "note": [
        "note_id", "person_id", "note_date", "note_datetime", "note_type_concept_id",
        "note_class_concept_id", "note_title", "note_text", "encoding_concept_id",
        "language_concept_id", "provider_id", "visit_occurrence_id", "visit_detail_id",
        "note_source_value",
    ],
}


def select_columns(df: pd.DataFrame, table: str, *, strict: bool = False) -> pd.DataFrame:
    """CDM 테이블의 표준 컬럼만, 표준 순서로 정렬해 반환한다.

    누락 컬럼은 ``strict=False`` 면 결측(NA)으로 채워 생성한다.
    """
    cols = CDM_COLUMNS[table]
    out = df.copy()
    missing = [c for c in cols if c not in out.columns]
    if missing:
        if strict:
            raise KeyError(f"[{table}] 누락 컬럼: {missing}")
        for c in missing:
            out[c] = pd.NA
    return out[cols]
