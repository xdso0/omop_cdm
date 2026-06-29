"""산출된 CDM 결과의 데이터 품질(QC) 검증.

OMOP CDM 산출물이 기본 규칙을 지키는지 점검하고 리포트를 출력한다.

검사 항목
  - PK(occurrence_id) 유일성·결측
  - person 외래키 정합성 (모든 person_id 가 person 테이블에 존재)
  - visit 외래키 정합성 (visit_occurrence_id 가 visit 에 존재)
  - 표준 concept 매핑률 (*_concept_id = 0 비율)
  - 날짜 범위 [2001-01-01, cutoff) 및 사망일 이후 사건 여부
  - 시작일 ≤ 종료일 (visit)

사용법::
    python scripts/validate_cdm.py --config input/sample/pipeline.sample.yaml

종료코드: 위반(ERROR) 이 하나라도 있으면 1, 아니면 0.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from omop_etl.config import load_config  # noqa: E402

# 테이블별 검사 스펙: pk, person fk 여부, 주요 날짜컬럼, concept 컬럼, visit fk 여부
SPEC = {
    "person":               {"pk": "person_id", "person_fk": False},
    "death":                {"pk": None, "person_fk": True, "date": "death_date"},
    "visit_occurrence":     {"pk": "visit_occurrence_id", "person_fk": True,
                             "date": "visit_start_date", "end": "visit_end_date"},
    "condition_occurrence": {"pk": "condition_occurrence_id", "person_fk": True,
                             "date": "condition_start_date", "concept": "condition_concept_id",
                             "visit_fk": True},
    "drug_exposure":        {"pk": "drug_exposure_id", "person_fk": True,
                             "date": "drug_exposure_start_date", "concept": "drug_concept_id",
                             "visit_fk": True},
    "procedure_occurrence": {"pk": "procedure_occurrence_id", "person_fk": True,
                             "date": "procedure_date", "concept": "procedure_concept_id"},
    "measurement":          {"pk": "measurement_id", "person_fk": True,
                             "date": "measurement_date", "concept": "measurement_concept_id",
                             "visit_fk": True},
    "observation":          {"pk": "observation_id", "person_fk": True,
                             "date": "observation_date", "concept": "observation_concept_id",
                             "visit_fk": True},
    "note":                 {"pk": "note_id", "person_fk": True, "date": "note_date",
                             "visit_fk": True},
}


def _load(out_root: Path, name: str) -> pd.DataFrame | None:
    for ext in (".parquet", ".csv"):
        p = out_root / f"{name}{ext}"
        if p.exists():
            return pd.read_parquet(p) if ext == ".parquet" else pd.read_csv(p)
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="CDM 산출물 QC 검증")
    ap.add_argument("--config", default=None)
    ap.add_argument("--output-root", default=None, help="검증할 산출 폴더(미지정 시 config)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    out_root = Path(args.output_root) if args.output_root else cfg.output_root
    cutoff = pd.Timestamp(year=2027, month=1, day=1)
    lo = pd.Timestamp("2001-01-01")
    print(f"검증 대상: {out_root}\n")

    person = _load(out_root, "person")
    person_ids = set(person["person_id"]) if person is not None else set()
    visit = _load(out_root, "visit_occurrence")
    visit_ids = set(visit["visit_occurrence_id"]) if visit is not None else set()
    death = _load(out_root, "death")
    death_map = (death.set_index("person_id")["death_date"] if death is not None else None)

    n_err = n_warn = 0

    def err(msg):
        nonlocal n_err; n_err += 1; print(f"  [ERROR] {msg}")

    def warn(msg):
        nonlocal n_warn; n_warn += 1; print(f"  [WARN ] {msg}")

    def ok(msg):
        print(f"  [ OK  ] {msg}")

    for name, spec in SPEC.items():
        df = _load(out_root, name)
        if df is None:
            continue
        print(f"■ {name}  ({len(df):,} rows)")

        # PK 유일성·결측
        pk = spec.get("pk")
        if pk and pk in df.columns:
            n_dup = df[pk].duplicated().sum()
            n_null = df[pk].isna().sum()
            (err if n_dup else ok)(f"PK {pk} 중복 {n_dup}건")
            if n_null:
                err(f"PK {pk} 결측 {n_null}건")

        # person 외래키
        if spec.get("person_fk") and person is not None and "person_id" in df.columns:
            miss = (~df["person_id"].isin(person_ids)).sum()
            (err if miss else ok)(f"person FK 누락 {miss}건")

        # visit 외래키 (NULL 허용, 값 있으면 존재해야)
        if spec.get("visit_fk") and visit is not None and "visit_occurrence_id" in df.columns:
            v = df["visit_occurrence_id"].dropna()
            miss = (~v.isin(visit_ids)).sum()
            (err if miss else ok)(f"visit FK 누락 {miss}건 (매칭 {len(v):,}/{len(df):,})")

        # concept 매핑률
        c = spec.get("concept")
        if c and c in df.columns:
            n0 = (pd.to_numeric(df[c], errors="coerce").fillna(0) == 0).sum()
            rate = 100 * (len(df) - n0) / len(df) if len(df) else 0
            (warn if n0 else ok)(f"{c} 표준매핑률 {rate:.1f}%  (미매핑 0: {n0:,}건)")

        # 날짜 범위 + 사망일 이후
        d = spec.get("date")
        if d and d in df.columns:
            dt = pd.to_datetime(df[d], errors="coerce")
            oob = ((dt < lo) | (dt >= cutoff)).sum()
            (warn if oob else ok)(f"날짜 {d} 범위밖 {oob}건  (min={dt.min()}, max={dt.max()})")
            if death_map is not None and "person_id" in df.columns:
                dd = df["person_id"].map(death_map)
                after = (dt > pd.to_datetime(dd)).sum()
                (err if after else ok)(f"사망일 이후 {d} {after}건")

        # 시작 ≤ 종료
        if spec.get("end") and spec["end"] in df.columns and d in df.columns:
            bad = (pd.to_datetime(df[d]) > pd.to_datetime(df[spec["end"]])).sum()
            (err if bad else ok)(f"시작>종료 {bad}건")
        print()

    print(f"결과: ERROR {n_err}건, WARN {n_warn}건")
    sys.exit(1 if n_err else 0)


if __name__ == "__main__":
    main()
