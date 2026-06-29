"""파이프라인 설정 로딩.

``config/pipeline.yaml`` 을 읽어 도메인별 경로/버전목록/채번코드/컷오프 등을
제공한다. 신규 연도(추출 배치)가 추가되면 YAML 의 해당 도메인 ``sources`` 에
한 줄만 추가하면 된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "pipeline.yaml"


@dataclass
class Source:
    """버전(추출 배치) 하나의 원천 데이터셋 정의."""

    folder: str          # mapping_root 하위 상대 폴더
    dataset: str         # 폴더 안의 sas7bdat 이름 (확장자 제외)
    hosp: int | None = None    # 1=site1, 2=site2 (None 이면 데이터에 이미 존재)
    options: dict[str, Any] = field(default_factory=dict)  # rename/drop 등 특수처리


@dataclass
class DomainConfig:
    name: str
    domain_code: str
    seq_width: int
    cutoff_year: int
    sources: list[Source]
    visit_match: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)  # cutoff_start/end 등 도메인 특수 키


@dataclass
class PipelineConfig:
    mapping_root: Path
    output_root: Path
    output_format: str
    sas_encoding: str
    domains: dict[str, DomainConfig]
    # --- Athena vocabulary ---
    vocab_root: Path | None = None
    athena_release: str = "unknown"
    unmapped_root: Path | None = None
    used_vocab_root: Path | None = None
    vocab_cache_root: Path | None = None
    vocab_mappings: dict[str, dict[str, Any]] = field(default_factory=dict)
    # --- DB 입출력 (선택) ---
    source_db: str | None = None      # 설정 시 소스를 DB 테이블에서 읽음(SQLAlchemy URL)
    source_schema: str | None = None
    output_db: str | None = None      # 설정 시 CDM 을 DB 에 저장(SQLAlchemy URL)
    output_schema: str | None = None
    stream_domains: list = field(default_factory=list)  # 청크 스트리밍으로 처리할 도메인
    chunksize: int = 500_000

    def path(self, *parts: str) -> Path:
        return self.mapping_root.joinpath(*parts)


def load_config(path: str | Path | None = None) -> PipelineConfig:
    cfg_path = Path(path) if path else _DEFAULT_CONFIG
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

    paths = raw.get("paths", {})
    domains: dict[str, DomainConfig] = {}
    _known = {"domain_code", "seq_width", "cutoff_year", "sources", "visit_match"}
    for name, d in raw.get("domains", {}).items():
        sources = [Source(**s) for s in d.get("sources", [])]
        domains[name] = DomainConfig(
            name=name,
            domain_code=str(d["domain_code"]),
            seq_width=int(d.get("seq_width", 5)),
            cutoff_year=int(d.get("cutoff_year", raw.get("cutoff_year", 2026))),
            sources=sources,
            visit_match=d.get("visit_match", {}),
            extra={k: v for k, v in d.items() if k not in _known},
        )

    output_root = Path(paths.get("output_root", "./output"))
    vocab = raw.get("vocabulary", {})
    release = str(vocab.get("athena_release", "unknown"))

    def _p(key: str, default: Path) -> Path:
        return Path(paths[key]) if paths.get(key) else default

    return PipelineConfig(
        mapping_root=Path(paths.get("mapping_root", ".")),
        output_root=output_root,
        output_format=paths.get("output_format", "parquet"),
        sas_encoding=raw.get("sas_encoding", "euc-kr"),
        domains=domains,
        vocab_root=_p("vocab_root", Path(".")) if paths.get("vocab_root") else None,
        athena_release=release,
        unmapped_root=_p("unmapped_root", output_root / "unmapped"),
        used_vocab_root=_p("used_vocab_root", output_root / "used_vocab"),
        vocab_cache_root=_p("vocab_cache_root", output_root / "_vocab_cache"),
        vocab_mappings=vocab.get("mappings", {}),
        source_db=paths.get("source_db"),
        source_schema=paths.get("source_schema"),
        output_db=paths.get("output_db"),
        output_schema=paths.get("output_schema"),
        stream_domains=raw.get("stream_domains", []),
        chunksize=int(raw.get("chunksize", 500_000)),
    )
