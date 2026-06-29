"""검사(lab) 항목 원천 → measurement 전처리.

원본은 검사 코드(L015273 등)마다 동일한 SAS 템플릿이 자동 생성돼
``measurement/<버전>/script/<code>.sas`` 형태로 수백 개 존재했다
(코드값 ``%let code=...`` 한 줄만 다름).

여기서는 이를 **하나의 함수 + 코드 리스트**로 대체한다.
검사 결과 raw 엑셀의 컬럼은 위치 기반이다.

==========  ==================================  ============================
원본 변수    위치(0-base)                         의미
==========  ==================================  ============================
_COL0       0                                   소속(병원 구분용)
_COL1       1                                   PERSON_ID
_COL5       5                                   측정일시 "YYYY-MM-DD HH:MM:SS"
_COL6       6                                   LocalCode
_COL8       8                                   결과값(value_source_value)
_COL9       9                                   provide
==========  ==================================  ============================

값 파싱 규칙(원본 그대로)
  - ``(`` ``)`` 등 괄호/특수문자 제거 후 숫자화
  - ``<`` 포함 → operator 4171756, 숫자만 추출
  - ``>`` 포함 → operator 4172704, 숫자만 추출
  - ``-`` / ``Negative`` → value_as_concept_id 9189
  - ``Positive`` → value_as_concept_id 9191
  - 'No WBC' → 0
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from ..io import read_excel

# 소속 명칭 → hosp 구분. site1_keyword 를 포함하면 1, 아니면 2.
def _hosp_from_dept(dept: pd.Series, site1_keyword: str = "") -> pd.Series:
    if not site1_keyword:
        return np.full(len(dept), 2)
    return np.where(dept.astype(str).str.contains(site1_keyword, na=False), 1, 2)


_NUM_RE = re.compile(r"[<>]")


def _to_number(s: str) -> float:
    s = re.sub(r"[()]", "", str(s))
    s = s.replace("<", "").replace(">", "")
    try:
        return float(s)
    except ValueError:
        return np.nan


def map_lab_item(raw_dir: str | Path, code: str, *, site1_keyword: str = "") -> pd.DataFrame:
    """검사 코드 하나의 raw 엑셀(``<raw_dir>/<code>.xlsx``)을 measurement 로 변환."""
    path = Path(raw_dir) / f"{code}.xlsx"
    raw = read_excel(path, sheet="Sheet1", header=None)

    col0, col1, col5 = raw[0], raw[1], raw[5]
    col6, col8, col9 = raw[6], raw[8], raw[9]

    out = pd.DataFrame()
    out["hosp"] = _hosp_from_dept(col0, site1_keyword)
    out["PERSON_ID"] = pd.to_numeric(col1, errors="coerce").astype("Int64")

    dt = pd.to_datetime(col5, errors="coerce")
    out["measurement_date"] = dt.dt.normalize()
    out["measurement_time"] = dt

    vsrc = col8.astype(str).str.replace(r"\s+", "", regex=True)
    out["value_source_value"] = vsrc
    out["provide"] = col9
    out["LocalCode"] = col6

    raw8 = col8.astype(str)
    tmp = raw8.str.replace(r"[()]", "", regex=True)
    tmp = tmp.where(tmp.ne("No WBC"), "0")

    has_lt = raw8.str.contains("<", na=False)
    has_gt = raw8.str.contains(">", na=False)
    is_neg = raw8.eq("-") | raw8.str.contains("Negative", na=False)
    is_pos = raw8.str.contains("Positive", na=False)

    out["operator_concept_id"] = np.select([has_lt, has_gt], [4171756, 4172704], default=np.nan)
    out["value_as_concept_id"] = np.select([is_neg, is_pos], [9189, 9191], default=np.nan)

    numeric = tmp.map(_to_number)
    # 부등호/양음성 아닌 일반 숫자만 value_as_number
    plain = ~(has_lt | has_gt | is_neg | is_pos)
    out["value_as_number"] = np.where(has_lt | has_gt, numeric, np.where(plain, numeric, np.nan))

    out["measurement_type_concept_id"] = 38000277
    out["range_low"] = np.nan
    out["range_high"] = np.nan
    out["measurement_source_concept_id"] = 0
    out["measurement_source_value"] = code

    # 빈 결과값 제거
    out = out[out["value_source_value"].ne("") & out["value_source_value"].notna()]
    return out.reset_index(drop=True)


def map_lab_items(raw_dir: str | Path, codes: list[str], *, site1_keyword: str = "") -> pd.DataFrame:
    """여러 검사 코드를 일괄 변환해 하나로 합친다.

    ``codes`` 는 raw_dir 폴더의 ``<code>.xlsx`` 목록. 비어 있으면 폴더 내 모든
    xlsx 를 자동 수집한다.
    """
    raw_dir = Path(raw_dir)
    if not codes:
        codes = sorted(p.stem for p in raw_dir.glob("*.xlsx"))
    frames = []
    for code in codes:
        try:
            frames.append(map_lab_item(raw_dir, code, site1_keyword=site1_keyword))
        except FileNotFoundError:
            continue
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)
