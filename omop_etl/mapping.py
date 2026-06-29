"""도메인 DataFrame 에 Athena 표준 매핑을 적용하는 통합 헬퍼.

- 원천 코드 컬럼 → 표준 concept_id + source_concept_id 부여 (표준만 사용)
- 매핑 실패(미매핑) 코드는 후속 작업용 폴더에 저장
- 사용한 concept_id 를 누적(used_concept_ids)해 vocab 정리에 활용
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .vocabulary import VocabStore


def _kcd7_code(s: str) -> str:
    """원천 condition_source_value → KCD7 concept_code 형식으로 정규화.

    예: ``A020|D00000009`` → ``A02.0`` (``|`` 앞부분만 취하고, 4자 이상이면
    3번째 문자 뒤에 점을 넣어 Athena KCD7 코드 형식과 맞춘다. R55 처럼 3자는 그대로).
    """
    code = str(s).split("|")[0].strip().upper()
    if len(code) > 3 and "." not in code:
        code = code[:3] + "." + code[3:]
    return code


# 코드 변환 레지스트리(config 의 code_transform 값 → 함수)
CODE_TRANSFORMS = {
    "kcd7": _kcd7_code,
    "split_pipe": lambda s: str(s).split("|")[0].strip(),
}


def apply_standard_mapping(
    df: pd.DataFrame,
    store: VocabStore,
    *,
    domain: str,
    source_col: str,
    vocab_id: str,
    concept_col: str,
    source_concept_col: str,
    unmapped_dir: str | Path | None = None,
    used_concept_ids: set | None = None,
    code_transform=None,
) -> pd.DataFrame:
    """``source_col`` 의 원천 코드를 Athena 표준 concept 로 매핑한다.

    Parameters
    ----------
    concept_col        : 표준 concept_id 를 채울 컬럼 (예: condition_concept_id)
    source_concept_col : source concept_id 를 채울 컬럼 (예: condition_source_concept_id)
    unmapped_dir       : 미매핑 코드를 저장할 폴더 (None 이면 저장 안 함)
    used_concept_ids   : 사용된 concept_id 누적 집합 (vocab 정리용)
    """
    # 원천 코드를 (필요 시) 어휘 코드 형식으로 변환 후 매핑
    key = df[source_col].astype(str)
    if code_transform is not None:
        key = key.map(code_transform)

    codes = key.dropna().unique()
    if len(codes) == 0:
        df[concept_col] = 0
        df[source_concept_col] = 0
        return df

    mapped = store.map_codes(codes, vocab_id)
    lut = mapped.set_index("source_code")

    df[concept_col] = key.map(lut["concept_id"]).fillna(0).astype("int64")
    df[source_concept_col] = key.map(lut["source_concept_id"]).fillna(0).astype("int64")

    # 미매핑 저장 (후속 작업용)
    unmapped = mapped[~mapped["mapped"]].copy()
    if unmapped_dir is not None and len(unmapped):
        out = Path(unmapped_dir)
        out.mkdir(parents=True, exist_ok=True)
        # 코드별 원천 건수
        vc = key.value_counts()
        unmapped["n_rows"] = unmapped["source_code"].map(vc).fillna(0).astype("int64")
        unmapped.insert(0, "vocabulary_id", vocab_id)
        unmapped.to_csv(out / f"{domain}_unmapped.csv", index=False, encoding="utf-8-sig")

    if used_concept_ids is not None:
        used_concept_ids.update(int(c) for c in mapped["concept_id"] if c)
        used_concept_ids.update(int(c) for c in mapped["source_concept_id"] if c)

    return df
