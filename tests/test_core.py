"""핵심 로직 단위 테스트.

pytest 가 있으면 ``pytest`` 로, 없으면 ``python tests/test_core.py`` 로 실행.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from omop_etl.ids import assign_occurrence_id, filter_person_id_length
from omop_etl.visit_match import match_visit_two_pass, match_visit_single
from omop_etl.person_filter import remove_after_death, keep_in_person_master
from omop_etl.vocabulary import VocabStore
from omop_etl.mapping import apply_standard_mapping


def test_occurrence_id():
    df = pd.DataFrame({
        "hosp": [1, 1, 2],
        "condition_start_date": pd.to_datetime(["2020-03-01", "2020-03-01", "2020-03-02"]),
        "condition_start_datetime": pd.to_datetime(
            ["2020-03-01 09:00", "2020-03-01 10:00", "2020-03-02 08:00"]),
    })
    out = assign_occurrence_id(df, id_col="cid", datetime_col="condition_start_datetime",
                              date_col="condition_start_date", domain_code="02", seq_width=5)
    assert out["cid"].tolist() == [12003010200001, 12003010200002, 22003020200001]


def test_person_id_length():
    df = pd.DataFrame({"PERSON_ID": [10000001, 123, 99999999]})
    assert set(filter_person_id_length(df)["PERSON_ID"]) == {10000001, 99999999}


def test_visit_two_pass_provider_priority():
    ev = pd.DataFrame({"PERSON_ID": [1], "provider_id": [7],
                       "condition_start_date": pd.to_datetime(["2020-01-05"])})
    vis = pd.DataFrame({"PERSON_ID": [1, 1], "visit_occurrence_id": [111, 222],
                        "visit_concept_id": [9201, 9202],
                        "visit_start_date": pd.to_datetime(["2020-01-01", "2020-01-01"]),
                        "visit_end_date": pd.to_datetime(["2020-01-10", "2020-01-10"]),
                        "provider_id": [99, 7]})
    m = match_visit_two_pass(ev, vis, date_col="condition_start_date",
                             window_pre_days=0, order_by_diff=False, null_9203_pass2=False)
    assert m["visit_occurrence_id"].iloc[0] == 222  # provider 일치 우선


def test_visit_single_9203_null():
    ev = pd.DataFrame({"PERSON_ID": [1], "observation_date": pd.to_datetime(["2020-01-05"])})
    vis = pd.DataFrame({"PERSON_ID": [1], "visit_occurrence_id": [9],
                        "visit_concept_id": [9203],
                        "visit_start_date": pd.to_datetime(["2020-01-01"]),
                        "visit_end_date": pd.to_datetime(["2020-01-10"]),
                        "provider_id": [1]})
    m = match_visit_single(ev, vis, date_col="observation_date", null_9203=True)
    assert pd.isna(m["visit_occurrence_id"].iloc[0])  # 9203 → NULL


def test_remove_after_death_and_master():
    person = pd.DataFrame({"PERSON_ID": [1, 2], "year_of_birth": [1980, 1990],
                           "month_of_birth": [1, 1]})
    death = pd.DataFrame({"PERSON_ID": [1], "death_date": pd.to_datetime(["2019-01-01"])})
    ev = pd.DataFrame({"PERSON_ID": [1, 2, 3],
                       "condition_start_date": pd.to_datetime(["2020-01-05", "2020-01-05", "2020-01-05"])})
    after = remove_after_death(ev, death, date_col="condition_start_date")
    assert set(after["PERSON_ID"]) == {2, 3}        # 1 은 사망 후 → 제거
    kept = keep_in_person_master(after, person)
    assert set(kept["PERSON_ID"]) == {2}            # 3 은 마스터에 없음 → 제거


def test_standard_mapping():
    tmp = Path(tempfile.mkdtemp())
    pd.DataFrame([
        [100, "x", "Condition", "KCD7", "c", "", "F32.9", "1970", "2099", ""],
        [9001, "y", "Condition", "SNOMED", "c", "S", "35489007", "1970", "2099", ""],
    ], columns=["concept_id", "concept_name", "domain_id", "vocabulary_id", "concept_class_id",
                "standard_concept", "concept_code", "valid_start_date", "valid_end_date",
                "invalid_reason"]).to_csv(tmp / "CONCEPT.csv", sep="\t", index=False)
    pd.DataFrame([[100, 9001, "Maps to", "1970", "2099", ""]],
                 columns=["concept_id_1", "concept_id_2", "relationship_id",
                          "valid_start_date", "valid_end_date", "invalid_reason"]).to_csv(
        tmp / "CONCEPT_RELATIONSHIP.csv", sep="\t", index=False)

    store = VocabStore(vocab_root=tmp, release="t", cache_root=tmp / "c")
    df = pd.DataFrame({"condition_source_value": ["F32.9", "ZZZ"]})
    out = apply_standard_mapping(df, store, domain="condition",
                                 source_col="condition_source_value", vocab_id="KCD7",
                                 concept_col="condition_concept_id",
                                 source_concept_col="condition_source_concept_id",
                                 unmapped_dir=tmp / "un")
    assert out["condition_concept_id"].tolist() == [9001, 0]      # 표준 매핑 / 미매핑
    assert out["condition_source_concept_id"].tolist() == [100, 0]
    assert (tmp / "un" / "condition_unmapped.csv").exists()       # 미매핑 보관


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  PASS  {fn.__name__}")
    print(f"\n{len(fns)}개 테스트 통과")


if __name__ == "__main__":
    _run_all()
