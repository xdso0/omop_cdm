"""도메인 모듈 공통 헬퍼.

버전(추출 배치)별 원천 sas7bdat 를 읽어 hosp 부여 / rename / drop /
PERSON_ID 정수화 / 연도·기간 필터 같은 배치별 특수처리를 적용하고 합친다.
원본 SAS 의 ``data aN; set libX.tbl; ... run;`` 묶음을 대체한다.
"""
from __future__ import annotations

import pandas as pd

from ..config import DomainConfig, PipelineConfig, Source
from ..io import read_sas

import pandas as _pd


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
    from ..mapping import apply_standard_mapping  # 지연 import (vocab 의존)

    return apply_standard_mapping(
        df, mapper,
        domain=domain,
        source_col=rule["source_col"],
        vocab_id=rule["source_vocabulary"],
        concept_col=rule["concept_col"],
        source_concept_col=rule["source_concept_col"],
        unmapped_dir=cfg.unmapped_root,
        used_concept_ids=used_concept_ids,
    )


def _first_date_col(df: pd.DataFrame) -> str:
    for c in df.columns:
        if c.endswith("_date"):
            return c
    raise KeyError("날짜 컬럼(*_date)을 찾지 못했습니다.")


def load_sources(
    domain: DomainConfig, cfg: PipelineConfig, *, group: str | None = None
) -> pd.DataFrame:
    """도메인의 모든 버전 소스를 읽어 하나로 합친다.

    Parameters
    ----------
    group : observation 처럼 'exam'/'inpatient' 그룹으로 나뉘는 경우 해당 그룹만 로드.
    """
    frames = []
    for src in domain.sources:
        if group is not None and (src.options or {}).get("group") != group:
            continue
        sas_path = cfg.path(src.folder, f"{src.dataset}.sas7bdat")
        csv_path = cfg.path(src.folder, f"{src.dataset}.csv")
        if sas_path.exists():
            df = read_sas(sas_path, encoding=cfg.sas_encoding)
        elif csv_path.exists():
            # 입력 템플릿(예시) 또는 CSV 원천 대비 폴백
            df = _pd.read_csv(csv_path)
        else:
            raise FileNotFoundError(f"원천 없음: {sas_path} (또는 .csv)")
        df = _apply_options(df, src, encoding=cfg.sas_encoding)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)
