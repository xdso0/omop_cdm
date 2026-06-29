"""Athena(OHDSI) vocabulary 기반 표준 개념 매핑 엔진.

Athena 에서 내려받은 vocabulary CSV(탭 구분)를 사용해 원천 코드를
**표준(standard_concept='S') concept_id** 로 매핑한다.

매핑 규칙
---------
원천 코드 ``code`` (vocabulary_id = ``V``) 에 대해:

1. CONCEPT 에서 ``vocabulary_id=V AND concept_code=code`` 인 source concept 를 찾는다.
2. 그 concept 가 이미 표준(``standard_concept='S'``)이면 그대로 사용.
3. 아니면 CONCEPT_RELATIONSHIP 의 ``relationship_id='Maps to'`` 로 표준 concept 로 변환.
4. 표준 매핑이 없으면 **미매핑**(concept_id=0)으로 분류해 별도 보관.

Athena 갱신 대응
----------------
새 Athena 추출본을 ``vocab_root`` 로 지정(또는 config 의 ``athena_release`` 변경)하면
전체 파이프라인이 새 vocabulary 를 따른다. 원천 vocabulary 별 필터 결과는
pickle 로 캐시되어(폴더명=release) 재실행이 빠르고, release 가 바뀌면 캐시도 분리된다.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

_CONCEPT_COLS = [
    "concept_id", "concept_name", "domain_id", "vocabulary_id",
    "concept_class_id", "standard_concept", "concept_code",
    "valid_start_date", "valid_end_date", "invalid_reason",
]
_REL_COLS = [
    "concept_id_1", "concept_id_2", "relationship_id",
    "valid_start_date", "valid_end_date", "invalid_reason",
]


def _read_tsv_chunks(path: Path, usecols=None, chunksize: int = 1_000_000):
    return pd.read_csv(
        path, sep="\t", dtype=str, usecols=usecols,
        chunksize=chunksize, na_filter=False, quoting=3,  # QUOTE_NONE
    )


@dataclass
class VocabStore:
    """Athena vocabulary 룩업 저장소.

    원천 vocabulary 별로 source concept(코드→concept) 와 Maps-to(비표준→표준)
    매핑을 lazy 하게 적재·캐시한다.
    """

    vocab_root: Path
    release: str = "unknown"
    cache_root: Path | None = None
    _src: dict[str, pd.DataFrame] = None        # vocab_id -> source concept df
    _maps: dict[str, dict[int, int]] = None     # vocab_id -> {source_cid: std_cid}

    def __post_init__(self):
        self.vocab_root = Path(self.vocab_root)
        if self.cache_root is not None:
            self.cache_root = Path(self.cache_root)
        self._src = {}
        self._maps = {}

    # ---------------- 적재 ----------------
    def _cache_path(self, name: str) -> Path | None:
        if self.cache_root is None:
            return None
        d = self.cache_root / self.release
        d.mkdir(parents=True, exist_ok=True)
        return d / name

    def _load_source_concepts(self, vocab_id: str) -> pd.DataFrame:
        if vocab_id in self._src:
            return self._src[vocab_id]

        cache = self._cache_path(f"src__{_safe(vocab_id)}.pkl")
        if cache is not None and cache.exists():
            df = pd.read_pickle(cache)
        else:
            frames = []
            for ch in _read_tsv_chunks(
                self.vocab_root / "CONCEPT.csv",
                usecols=["concept_id", "vocabulary_id", "standard_concept",
                         "concept_code", "domain_id", "invalid_reason"],
            ):
                sub = ch[(ch["vocabulary_id"] == vocab_id) & (ch["invalid_reason"] == "")]
                if len(sub):
                    frames.append(sub)
            df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
                columns=["concept_id", "vocabulary_id", "standard_concept",
                         "concept_code", "domain_id", "invalid_reason"]
            )
            df["concept_id"] = pd.to_numeric(df["concept_id"], errors="coerce").astype("Int64")
            if cache is not None:
                df.to_pickle(cache)

        self._src[vocab_id] = df
        return df

    def _load_maps_to(self, source_cids: set[int]) -> dict[int, int]:
        """주어진 source concept_id 집합의 'Maps to' 대상(표준)을 적재."""
        result: dict[int, int] = {}
        for ch in _read_tsv_chunks(
            self.vocab_root / "CONCEPT_RELATIONSHIP.csv",
            usecols=["concept_id_1", "concept_id_2", "relationship_id", "invalid_reason"],
        ):
            sub = ch[(ch["relationship_id"] == "Maps to") & (ch["invalid_reason"] == "")]
            if not len(sub):
                continue
            c1 = pd.to_numeric(sub["concept_id_1"], errors="coerce")
            c2 = pd.to_numeric(sub["concept_id_2"], errors="coerce")
            for a, b in zip(c1, c2):
                if a in source_cids and pd.notna(b):
                    result[int(a)] = int(b)
        return result

    # ---------------- 매핑 ----------------
    def map_codes(self, codes: Iterable[str], vocab_id: str) -> pd.DataFrame:
        """원천 코드 목록을 표준 concept 로 매핑한 결과 DataFrame 반환.

        columns: source_code, source_concept_id, concept_id, mapped(bool)
        """
        codes = pd.Index(pd.unique(pd.Series(list(codes), dtype="object").dropna()))
        src = self._load_source_concepts(vocab_id)
        by_code = src.dropna(subset=["concept_id"]).drop_duplicates("concept_code")
        by_code = by_code.set_index("concept_code")

        rows = []
        nonstd_cids: set[int] = set()
        info: dict[str, tuple] = {}
        for code in codes:
            key = str(code)
            if key not in by_code.index:
                info[key] = (0, 0, False)  # source 자체가 없음
                continue
            cid = int(by_code.at[key, "concept_id"])
            std = by_code.at[key, "standard_concept"]
            if std == "S":
                info[key] = (cid, cid, True)
            else:
                nonstd_cids.add(cid)
                info[key] = (cid, None, None)  # 표준 변환 보류

        if nonstd_cids:
            maps = self._cached_maps(vocab_id, nonstd_cids)
            for key, val in list(info.items()):
                if val[1] is None:  # 보류였던 항목
                    src_cid = val[0]
                    tgt = maps.get(src_cid)
                    info[key] = (src_cid, tgt if tgt else 0, bool(tgt))

        for key, (src_cid, std_cid, mapped) in info.items():
            rows.append({
                "source_code": key,
                "source_concept_id": src_cid,
                "concept_id": std_cid if std_cid else 0,
                "mapped": bool(mapped),
            })
        return pd.DataFrame(rows, columns=["source_code", "source_concept_id", "concept_id", "mapped"])

    def _cached_maps(self, vocab_id: str, nonstd_cids: set[int]) -> dict[int, int]:
        cache = self._cache_path(f"mapsto__{_safe(vocab_id)}.pkl")
        if cache is not None and cache.exists():
            m = pd.read_pickle(cache)
            full = dict(zip(m["src"].astype(int), m["tgt"].astype(int)))
            missing = nonstd_cids - set(full)
            if not missing:
                return full
            full.update(self._load_maps_to(missing))
            pd.DataFrame({"src": list(full), "tgt": list(full.values())}).to_pickle(cache)
            return full
        full = self._load_maps_to(nonstd_cids)
        if cache is not None:
            pd.DataFrame({"src": list(full), "tgt": list(full.values())}).to_pickle(cache)
        return full


def _safe(name: str) -> str:
    return name.replace(" ", "_").replace("/", "_")


# --------------------------------------------------------------------- #
# 사용한 vocabulary 정리 (DB 적재용)
# --------------------------------------------------------------------- #
def export_used_vocab(
    vocab_root: str | Path,
    used_concept_ids: set[int],
    out_dir: str | Path,
) -> dict[str, Path]:
    """파이프라인에서 실제 사용한 concept 만 골라 vocabulary 서브셋으로 저장.

    이후 DB(CONCEPT / CONCEPT_RELATIONSHIP / VOCABULARY) 에 적재해
    CDM 테이블과 조인해 쓸 수 있다.

    저장 파일: CONCEPT.csv, CONCEPT_RELATIONSHIP.csv, VOCABULARY.csv (탭 구분)
    """
    vocab_root = Path(vocab_root)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    used = {int(c) for c in used_concept_ids if c and int(c) != 0}

    # 1) CONCEPT 서브셋
    concept_frames, used_vocabs = [], set()
    for ch in _read_tsv_chunks(vocab_root / "CONCEPT.csv"):
        cid = pd.to_numeric(ch["concept_id"], errors="coerce")
        sub = ch[cid.isin(used)]
        if len(sub):
            concept_frames.append(sub)
            used_vocabs.update(sub["vocabulary_id"].unique())
    concept = pd.concat(concept_frames, ignore_index=True) if concept_frames else pd.DataFrame(columns=_CONCEPT_COLS)
    concept_path = out_dir / "CONCEPT.csv"
    concept.to_csv(concept_path, sep="\t", index=False)

    # 2) CONCEPT_RELATIONSHIP 서브셋 (사용 concept 들 간 관계만)
    rel_frames = []
    for ch in _read_tsv_chunks(vocab_root / "CONCEPT_RELATIONSHIP.csv"):
        c1 = pd.to_numeric(ch["concept_id_1"], errors="coerce")
        c2 = pd.to_numeric(ch["concept_id_2"], errors="coerce")
        sub = ch[c1.isin(used) & c2.isin(used)]
        if len(sub):
            rel_frames.append(sub)
    rel = pd.concat(rel_frames, ignore_index=True) if rel_frames else pd.DataFrame(columns=_REL_COLS)
    rel_path = out_dir / "CONCEPT_RELATIONSHIP.csv"
    rel.to_csv(rel_path, sep="\t", index=False)

    # 3) VOCABULARY 서브셋
    vocab_path = out_dir / "VOCABULARY.csv"
    vocab_src = vocab_root / "VOCABULARY.csv"
    if vocab_src.exists():
        vdf = pd.read_csv(vocab_src, sep="\t", dtype=str, na_filter=False, quoting=3)
        vdf[vdf["vocabulary_id"].isin(used_vocabs)].to_csv(vocab_path, sep="\t", index=False)

    return {"concept": concept_path, "concept_relationship": rel_path, "vocabulary": vocab_path}
