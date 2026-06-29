"""입출력 유틸리티.

원천 데이터(`*.sas7bdat`, `*.xlsx`, `*.csv`)를 pandas DataFrame 으로 읽고,
CDM 산출물을 parquet/csv 로 저장한다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pandas as pd

try:  # pyreadstat 은 .sas7bdat 입출력에만 필요 (없어도 xlsx/csv 는 동작)
    import pyreadstat
except ImportError:  # pragma: no cover
    pyreadstat = None


# --------------------------------------------------------------------- #
# 읽기
# --------------------------------------------------------------------- #
# 한글 .sas7bdat 인코딩 폴백 순서. 파일마다 euc-kr/cp949 가 섞여 있고
# 일부는 잘못된 바이트가 있어, 주어진 인코딩 → cp949(상위호환) → 자동(None)
# → latin1(최후, 무손실 바이트 매핑) 순으로 시도한다.
def _encoding_candidates(encoding: str | None) -> list:
    seq = [encoding, "cp949", "ms949", None, "latin1"]
    seen, out = set(), []
    for e in seq:
        key = e or "__auto__"
        if key not in seen:
            seen.add(key); out.append(e)
    return out


def _resolve_usecols(path: str | Path, usecols, encoding: str | None) -> list | None:
    """원하는 컬럼(소문자 집합)을 파일 실제 컬럼명(대소문자 무관)으로 매핑.

    메타데이터만 먼저 읽어(빠름) 실제 존재하는 컬럼만 골라 반환한다.
    """
    if not usecols:
        return None
    want = {c.lower() for c in usecols}
    last = None
    for enc in _encoding_candidates(encoding):
        try:
            kw = {"metadataonly": True}
            if enc is not None:
                kw["encoding"] = enc
            _df, meta = pyreadstat.read_sas7bdat(str(path), **kw)
            return [c for c in meta.column_names if c.lower() in want]
        except Exception as e:
            last = e
    raise last


# --------------------------------------------------------------------- #
def read_sas(
    path: str | Path, *, encoding: str = "euc-kr", usecols=None
) -> pd.DataFrame:
    """SAS `.sas7bdat` 파일을 DataFrame 으로 읽는다.

    한글이 포함된 데이터셋은 보통 ``euc-kr``/``cp949`` 로 저장돼 있다. 지정 인코딩이
    실패하면 자동으로 다른 인코딩으로 재시도한다.

    usecols : 읽을 컬럼(소문자 집합/리스트). 대소문자 무시. 메모리 절감용으로
              필요한 컬럼만 읽는다. 없는 컬럼은 무시.
    """
    if pyreadstat is None:
        raise ImportError("pyreadstat 가 필요합니다: pip install pyreadstat")
    cols = _resolve_usecols(path, usecols, encoding)
    last = None
    for enc in _encoding_candidates(encoding):
        try:
            kw = {} if enc is None else {"encoding": enc}
            if cols is not None:
                kw["usecols"] = cols
            df, _meta = pyreadstat.read_sas7bdat(str(path), **kw)
            return df
        except Exception as e:  # 인코딩 오류 시 다음 후보로
            last = e
    raise last


def read_sas_chunks(
    path: str | Path, *, chunksize: int = 500_000, encoding: str = "euc-kr", usecols=None
) -> Iterator[pd.DataFrame]:
    """대용량 `.sas7bdat`(수십 GB) 를 청크 단위로 읽는다(필요 컬럼만)."""
    if pyreadstat is None:
        raise ImportError("pyreadstat 가 필요합니다: pip install pyreadstat")
    cols = _resolve_usecols(path, usecols, encoding)
    last = None
    for enc in _encoding_candidates(encoding):
        try:
            kw = {} if enc is None else {"encoding": enc}
            if cols is not None:
                kw["usecols"] = cols
            reader = pyreadstat.read_file_in_chunks(
                pyreadstat.read_sas7bdat, str(path), chunksize=chunksize, **kw
            )
            for df, _meta in reader:
                yield df
            return
        except Exception as e:
            last = e
    raise last


def downcast_integers(df: pd.DataFrame) -> pd.DataFrame:
    """정수로 표현 가능하고 결측이 없는 float 컬럼만 일반 정수형으로 다운캐스트.

    PERSON_ID·concept_id 등 원천에서 float64 로 들어온 정수 컬럼의 메모리를 줄인다.
    결측(NaN)이 있는 컬럼은 그대로 둔다(nullable Int 로 바꾸면 이후 불리언 연산에서
    NA 모호성 오류가 나므로). 실수값(소수점)은 보존한다.
    """
    for c in df.columns:
        s = df[c]
        if s.dtype != "float64" or s.isna().any():
            continue
        if len(s) and (s == s.round()).all():
            df[c] = pd.to_numeric(s, downcast="integer")
    return df


def read_excel(path: str | Path, sheet: str | int = 0, **kw) -> pd.DataFrame:
    """Excel 시트를 DataFrame 으로 읽는다."""
    return pd.read_excel(path, sheet_name=sheet, **kw)


def read_table(path: str | Path, **kw) -> pd.DataFrame:
    """확장자로 포맷을 판별해 읽는다 (sas7bdat / xlsx / csv / parquet)."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".sas7bdat":
        return read_sas(p, **kw)
    if ext in {".xlsx", ".xls"}:
        return read_excel(p, **kw)
    if ext == ".csv":
        return pd.read_csv(p, **kw)
    if ext in {".parquet", ".pq"}:
        return pd.read_parquet(p, **kw)
    raise ValueError(f"지원하지 않는 확장자: {ext}")


# --------------------------------------------------------------------- #
# 쓰기
# --------------------------------------------------------------------- #
def write_cdm(df: pd.DataFrame, path: str | Path, *, fmt: str = "parquet") -> Path:
    """CDM 테이블을 저장한다.

    기본은 parquet (대용량·타입 보존). ``fmt='csv'`` 도 가능.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "parquet":
        out = p.with_suffix(".parquet")
        df.to_parquet(out, index=False)
    elif fmt == "csv":
        out = p.with_suffix(".csv")
        df.to_csv(out, index=False, encoding="utf-8-sig")
    elif fmt == "sas7bdat":
        if pyreadstat is None:
            raise ImportError("pyreadstat 가 필요합니다.")
        out = p.with_suffix(".sas7bdat")
        pyreadstat.write_sas7bdat(df, str(out))
    else:
        raise ValueError(f"지원하지 않는 포맷: {fmt}")
    return out
