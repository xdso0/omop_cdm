"""대상자(person) 관련 공통 필터·검증.

모든 도메인 join 스크립트가 동일하게 수행하는 단계를 모은 모듈이다.

1. :func:`apply_cutoff`          - 컷오프 연도 이후 데이터 제거
2. :func:`remove_after_death`    - 사망일 이후 사건 제거
3. :func:`load_excluded_persons` / :func:`exclude_persons`
                                 - person_id.xlsx(Sheet2) 의 '삭제' 대상자 제외
4. :func:`validate_against_person` - person 마스터 정합성 검증(검증 리스트 산출)
5. :func:`keep_in_person_master` - person 마스터에 존재하는 행만 유지
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .io import read_excel


def apply_cutoff(df: pd.DataFrame, *, date_col: str, cutoff_year: int) -> pd.DataFrame:
    """``date_col < {cutoff_year}-01-01`` 인 행만 남긴다.

    SAS ``if <date> < mdy(1,1,&cutoff_year.);`` 대응.
    """
    cutoff = pd.Timestamp(year=cutoff_year, month=1, day=1)
    return df[pd.to_datetime(df[date_col]) < cutoff].copy()


def remove_after_death(
    df: pd.DataFrame,
    death: pd.DataFrame,
    *,
    date_col: str,
    person_col: str = "PERSON_ID",
) -> pd.DataFrame:
    """사망일 이후 발생한 사건을 제거한다.

    SAS: death 를 left join 후 ``if death_date=. or <date> <= death_date;``.
    """
    dd = death[[person_col, "death_date"]].drop_duplicates(person_col)
    merged = df.merge(dd, on=person_col, how="left")
    keep = merged["death_date"].isna() | (
        pd.to_datetime(merged[date_col]) <= pd.to_datetime(merged["death_date"])
    )
    return merged[keep].drop(columns="death_date").copy()


def load_excluded_persons(
    person_id_xlsx: str | Path, *, sheet: str = "Sheet2"
) -> set:
    """제외 대상자(PERSON_ID) 집합을 읽는다.

    SAS: ``if index(name,'삭제')>0 and year_of_birth<1900`` 인 사람.
    (이름이 '삭제'로 표시되고 출생연도가 비정상인, 정제 과정에서 폐기된 ID)
    """
    pp = read_excel(person_id_xlsx, sheet=sheet)
    cols = {c.lower(): c for c in pp.columns}
    name_c = cols.get("name", "name")
    yob_c = cols.get("year_of_birth", "year_of_birth")
    pid_c = cols.get("person_id", "PERSON_ID")
    mask = pp[name_c].astype(str).str.contains("삭제", na=False) & (
        pd.to_numeric(pp[yob_c], errors="coerce") < 1900
    )
    return set(pd.to_numeric(pp.loc[mask, pid_c], errors="coerce").dropna().astype("int64"))


def exclude_persons(
    df: pd.DataFrame, excluded: set, *, person_col: str = "PERSON_ID"
) -> pd.DataFrame:
    """제외 대상 PERSON_ID 를 가진 행을 버린다."""
    return df[~df[person_col].isin(excluded)].copy()


def validate_against_person(
    df: pd.DataFrame,
    person: pd.DataFrame,
    *,
    date_col: str | None = None,
    person_col: str = "PERSON_ID",
) -> pd.DataFrame:
    """person 마스터와의 정합성 위반 PERSON_ID 목록을 반환(검증용 export 대상).

    위반 조건
      - person 마스터에 없는 PERSON_ID, 또는
      - 출생연월이 사건 발생일보다 늦은 경우(미래 출생).
    """
    p = person[[person_col, "year_of_birth", "month_of_birth"]].drop_duplicates(person_col)
    merged = df.merge(p, on=person_col, how="left")

    missing = merged["year_of_birth"].isna()
    bad = missing
    if date_col is not None:
        d = pd.to_datetime(merged[date_col])
        born_after = (merged["year_of_birth"] > d.dt.year) | (
            merged["year_of_birth"].eq(d.dt.year) & (merged["month_of_birth"] > d.dt.month)
        )
        bad = missing | born_after
    return merged.loc[bad, [person_col]].drop_duplicates().reset_index(drop=True)


def keep_in_person_master(
    df: pd.DataFrame, person: pd.DataFrame, *, person_col: str = "PERSON_ID"
) -> pd.DataFrame:
    """person 마스터에 존재하는 PERSON_ID 의 행만 남긴다 (inner join)."""
    valid = person[[person_col]].drop_duplicates()
    return df.merge(valid, on=person_col, how="inner")


def load_person_overrides(person_id_xlsx: str | Path, *, sheet: str = "Sheet2") -> pd.DataFrame:
    """person 정제용 성별 보정 테이블(Sheet2)을 읽어 gender_concept_id 를 부여한다.

    SAS: ``if sex='남' then 8507; else if sex='여' then 8532;``
    """
    pp = read_excel(person_id_xlsx, sheet=sheet)
    pp["gender_concept_id"] = pp.get("sex").map({"남": 8507, "여": 8532})
    return pp
