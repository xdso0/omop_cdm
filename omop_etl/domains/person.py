"""PERSON 도메인.

처리 순서
  1) 버전 통합 — 동일 PERSON_ID 는 먼저 등장한 버전 우선(신규만 추가)
  2) 보정 엑셀(person_id.xlsx Sheet2, pp1) 로 gender/출생연월 덮어쓰기
  3) '삭제' 대상자(pp2) 제외
  4) 상수 컬럼/성별 source 설정
  5) (선택) 가명 ID(PID) 매핑 → person_m
  6) 최종 컬럼 선택 및 검증 리스트 산출
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..cdm_schema import select_columns
from ..config import PipelineConfig
from ..io import read_excel, read_table
from ._common import load_sources


def _norm_pid(df: pd.DataFrame) -> pd.DataFrame:
    if "person_id" in df.columns and "PERSON_ID" not in df.columns:
        df = df.rename(columns={"person_id": "PERSON_ID"})
    return df


def build(
    cfg: PipelineConfig,
    *,
    person_id_xlsx: str | Path,
    pseudo_id_path: str | Path | None = None,
) -> dict:
    dom = cfg.domains["person"]
    b = _norm_pid(load_sources(dom, cfg))

    # 1) 버전 통합: 먼저 등장한 PERSON_ID 우선
    b = b[b["PERSON_ID"].notna()]
    b = b.drop_duplicates("PERSON_ID", keep="first")
    # location_id 큰 값 우선(location_id 큰 값 우선)
    if "location_id" in b.columns:
        b = b.sort_values(["PERSON_ID", "location_id"], ascending=[True, False])
        b = b.drop_duplicates("PERSON_ID", keep="first")

    # gender 0 -> 결측
    if "gender_concept_id" in b.columns:
        b.loc[b["gender_concept_id"].eq(0), "gender_concept_id"] = pd.NA

    # 2~3) 보정 엑셀 로드
    pp1 = _norm_pid(read_excel(person_id_xlsx, sheet="Sheet2"))
    pp1["gender_concept_id"] = pp1.get("sex").map({"남": 8507, "여": 8532})
    pp1 = pp1[pp1["PERSON_ID"].notna()]
    excl = pp1[
        pp1.get("name", "").astype(str).str.contains("삭제", na=False)
        & (pd.to_numeric(pp1.get("year_of_birth"), errors="coerce") < 1900)
    ]["PERSON_ID"]

    ovr = pp1[["PERSON_ID", "gender_concept_id", "year_of_birth", "month_of_birth"]]
    merged = b.merge(ovr, on="PERSON_ID", how="outer", suffixes=("", "_ovr"))
    merged = merged[~merged["PERSON_ID"].isin(set(excl))]
    for col in ["gender_concept_id", "year_of_birth", "month_of_birth"]:
        ovr_col = f"{col}_ovr"
        if ovr_col in merged.columns:
            merged[col] = merged[ovr_col].combine_first(merged.get(col))
            merged = merged.drop(columns=ovr_col)

    # 4) 상수/파생 컬럼
    merged["gender_source_value"] = merged["gender_concept_id"].map(
        {8507: "Male", 8532: "Female"}
    ).fillna("")
    merged["location_id"] = merged.get("location_id").fillna(0) if "location_id" in merged else 0
    merged["provider_id"] = 0
    merged["care_site_id"] = 0
    merged["person_source_value"] = ""
    merged["race_source_value"] = ""
    merged["race_source_concept_id"] = 0
    merged["ethnicity_source_value"] = ""
    merged["ethnicity_source_concept_id"] = 0
    merged["birth_datetime"] = pd.NaT
    merged = merged[merged["PERSON_ID"].notna()]

    # 5) 가명 ID 매핑 (선택)
    person_m = None
    if pseudo_id_path is not None and Path(pseudo_id_path).exists():
        pmap = _norm_pid(read_table(pseudo_id_path))
        merged = merged.merge(pmap[["PERSON_ID", "PID"]], on="PERSON_ID", how="left")
        person_m = merged[["PERSON_ID", "PID"]].rename(columns={"PERSON_ID": "person_id", "PID": "pid"})

    # 6) 최종 + 검증
    out = merged.rename(columns={"PERSON_ID": "person_id"})
    person = select_columns(out, "person").drop_duplicates("person_id")

    yob = pd.to_numeric(person["year_of_birth"], errors="coerce")
    invalid = person.loc[yob.isna() | (yob < 1900), ["person_id"]]
    dup = person["person_id"].value_counts()
    duplicated = dup[dup >= 2].index.to_frame(name="person_id").reset_index(drop=True)

    return {
        "person": person,
        "person_m": person_m,
        "invalid_person_id": invalid,
        "duplicated_person_id": duplicated,
    }
