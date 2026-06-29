"""omop-cdm-etl
================
EMR/OCS 원천 데이터를 OMOP CDM(v5.x)으로 변환하는 ETL 패키지.

기존 SAS(`*_join.sas`) + 버전별 전처리(`step01.sas` 등) 로직을 재사용 가능한
Python 모듈로 재구성한 것이다.

구성
----
- :mod:`omop_etl.io`            : SAS/Excel/CSV 입출력
- :mod:`omop_etl.ids`           : OMOP 기본키(occurrence_id) 채번
- :mod:`omop_etl.visit_match`   : 방문(visit) 매칭
- :mod:`omop_etl.person_filter` : 사망일/대상자 필터, person 마스터 정합성 검증
- :mod:`omop_etl.cdm_schema`    : OMOP CDM 테이블 컬럼 정의
- :mod:`omop_etl.config`        : 파이프라인 설정 로딩
- :mod:`omop_etl.domains`       : 도메인별 ETL (person, visit, condition, drug, ...)
- :mod:`omop_etl.preprocessing` : 버전별 원천 전처리(검사 항목 매핑 등)
"""

__version__ = "0.1.0"
