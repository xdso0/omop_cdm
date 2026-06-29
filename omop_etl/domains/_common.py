"""도메인 모듈 공통 헬퍼.

버전(추출 배치)별 원천 sas7bdat 를 읽어 hosp 부여 / rename / drop /
PERSON_ID 정수화 / 연도·기간 필터 같은 배치별 특수처리를 적용하고 합친다.
원본 SAS 의 ``data aN; set libX.tbl; ... run;`` 묶음을 대체한다.
"""
from __future__ import annotations

import pandas as pd

from ..config import DomainConfig, PipelineConfig, Source
from ..io import read_sas, downcast_integers

import pandas as _pd


# 도메인별로 원천에서 읽을 컬럼(소문자). 메모리 절감을 위해 필요한 것만 읽는다.
# (rename 원본키·person_id 는 _source_usecols 가 자동 추가, 없는 컬럼은 무시)
SOURCE_COLUMNS: dict[str, list[str]] = {
    "person": ["person_id", "gender_concept_id", "year_of_birth", "month_of_birth",
               "day_of_birth", "race_concept_id", "ethnicity_concept_id", "location_id"],
    "death": ["person_id", "death_date", "death_datetime", "death_type_concept_id",
              "cause_concept_id", "cause_source_value", "cause_source_concept_id"],
    "visit": ["person_id", "visit_concept_id", "visit_start_date", "visit_start_time",
              "visit_end_date", "visit_end_time", "provider_id", "care_site_id",
              "payer_source_value", "plan_source_value", "hosp"],
    "condition": ["person_id", "condition_concept_id", "condition_start_date",
                  "condition_start_datetime", "condition_end_date", "condition_end_datetime",
                  "condition_type_concept_id", "stop_reason", "provider_id",
                  "condition_source_value", "condition_source_concept_id", "hosp"],
    "drug": ["person_id", "conceptid", "drug_exposure_start_date", "drug_exposure_start_datetime",
             "drug_exposure_end_date", "drug_exposure_end_datetime", "drug_type_concept_id",
             "quantity_days", "days_supply", "route_concept_id", "provider_id",
             "drug_source_value", "hosp"],
    "procedure": ["person_id", "procedure_concept_id", "procedure_date", "procedure_datetime",
                  "procedure_type_concept_id", "quantity", "provider_id",
                  "procedure_source_value", "procedure_source_concept_id", "edi_code", "hosp"],
    "observation": ["person_id", "observation_concept_id", "observation_date", "observation_time",
                    "observation_type_concept_id", "value_as_number", "value_as_string",
                    "value_as_concept_id", "qualifier_concept_id", "unit_concept_id",
                    "provider_id", "observation_source_value", "observation_source_concept_id",
                    "unit_source_value", "qualifier_source_value", "name", "hosp"],
    "note": ["person_id", "note_date", "note_datetime", "note_type_concept_id",
             "note_class_concept_id", "note_title", "note_text", "encoding_concept_id",
             "language_concept_id", "provider_id", "note_source_value", "hosp"],
    "measurement": ["person_id", "measurement_concept_id", "measurement_date", "measurement_time",
                    "measurement_datetime", "measurement_type_concept_id", "operator_concept_id",
                    "value_as_number", "value_as_concept_id", "unit_concept_id", "unitconceptid",
                    "range_low", "range_high", "provider_id", "measurement_source_value",
                    "measurement_source_concept_id", "unit_source_value", "value_source_value",
                    "hosp"],
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """컬럼명을 소문자로 통일(SAS 는 대소문자 무시하나 pandas 는 구분).

    소스마다 visit_start_date / VISIT_START_DATE 처럼 케이스가 달라 합칠 때
    서로 다른 컬럼으로 취급되는 문제를 막는다. PERSON_ID 만 대문자 규칙 유지.
    """
    df = df.copy()
    df.columns = [str(c).lower() for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]
    if "person_id" in df.columns:
        df = df.rename(columns={"person_id": "PERSON_ID"})
    return df


def _apply_options(df: pd.DataFrame, src: Source, *, encoding: str) -> pd.DataFrame:
    opts = src.options or {}

    if src.hosp is not None:
        df["hosp"] = src.hosp

    if opts.get("int_person_id"):
        # SAS: ppp=int(person_id); if ppp=. then delete;
        pid = pd.to_numeric(df.get("person_id", df.get("PERSON_ID")), errors="coerce")
        df = df.assign(PERSON_ID=pid.astype("Int64"))
        df = df[df["PERSON_ID"].notna()]
        df = df.drop(columns=[c for c in ["person_id"] if c in df.columns and c != "PERSON_ID"])

    if "drop" in opts:
        df = df.drop(columns=[c for c in opts["drop"] if c in df.columns])

    if "rename" in opts:
        df = df.rename(columns=opts["rename"])

    if "year_min" in opts:
        # 날짜 컬럼은 도메인마다 다르므로 첫 *_date 컬럼 기준
        dcol = _first_date_col(df)
        df = df[pd.to_datetime(df[dcol]).dt.year >= int(opts["year_min"])]

    if "date_between" in opts:
        lo, hi = opts["date_between"]
        dcol = _first_date_col(df)
        d = pd.to_datetime(df[dcol])
        df = df[(d >= pd.Timestamp(lo)) & (d <= pd.Timestamp(hi))]

    return df


def maybe_map_standard(
    df: _pd.DataFrame,
    cfg: PipelineConfig,
    domain: str,
    mapper,
    used_concept_ids,
) -> _pd.DataFrame:
    """config.vocab_mappings 에 도메인 규칙이 있고 mapper 가 주어지면 표준 매핑 적용.

    규칙이 없거나 mapper 가 없으면(=vocab 미사용) 원본 df 를 그대로 반환한다.
    """
    rule = cfg.vocab_mappings.get(domain)
    if not rule or mapper is None:
        return df
    from ..mapping import apply_standard_mapping, CODE_TRANSFORMS  # 지연 import

    transform = CODE_TRANSFORMS.get(rule.get("code_transform"))
    return apply_standard_mapping(
        df, mapper,
        domain=domain,
        source_col=rule["source_col"],
        vocab_id=rule["source_vocabulary"],
        concept_col=rule["concept_col"],
        source_concept_col=rule["source_concept_col"],
        unmapped_dir=cfg.unmapped_root,
        used_concept_ids=used_concept_ids,
        code_transform=transform,
    )


def _first_date_col(df: pd.DataFrame) -> str:
    for c in df.columns:
        if c.endswith("_date"):
            return c
    raise KeyError("날짜 컬럼(*_date)을 찾지 못했습니다.")


def _source_usecols(usecols, opts: dict) -> set | None:
    """소스에서 실제로 읽을 컬럼 집합. usecols + rename 원본키 + person_id 포함."""
    if not usecols:
        return None
    want = {c.lower() for c in usecols}
    want |= {k.lower() for k in (opts.get("rename") or {})}  # rename 원본 컬럼도 읽어야 함
    want |= {"person_id"}                                    # 정규화/검증용 항상 포함
    return want


def load_sources(
    domain: DomainConfig, cfg: PipelineConfig, *, group: str | None = None, usecols=None
) -> pd.DataFrame:
    """도메인의 모든 버전 소스를 읽어 하나로 합친다.

    Parameters
    ----------
    group   : observation 처럼 'exam'/'inpatient' 그룹으로 나뉘는 경우 해당 그룹만.
    usecols : 읽을 컬럼(소문자). 지정 시 필요한 컬럼만 읽어 메모리를 줄인다.
    """
    if usecols is None:
        usecols = SOURCE_COLUMNS.get(domain.name)   # 도메인 기본 컬럼 자동 적용
    frames = []
    for src in domain.sources:
        if group is not None and (src.options or {}).get("group") != group:
            continue
        cols = _source_usecols(usecols, src.options or {})
        sas_path = cfg.path(src.folder, f"{src.dataset}.sas7bdat")
        csv_path = cfg.path(src.folder, f"{src.dataset}.csv")
        if sas_path.exists():
            df = read_sas(sas_path, encoding=cfg.sas_encoding, usecols=cols)
        elif csv_path.exists():
            # 입력 템플릿(예시) 또는 CSV 원천 대비 폴백
            df = _pd.read_csv(csv_path)
        else:
            raise FileNotFoundError(f"원천 없음: {sas_path} (또는 .csv)")
        df = _normalize_columns(df)          # 컬럼명 소문자 통일 (케이스 불일치 방지)
        df = _apply_options(df, src, encoding=cfg.sas_encoding)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    del frames
    return downcast_integers(out)            # 정수형 다운캐스트로 메모리 절감
