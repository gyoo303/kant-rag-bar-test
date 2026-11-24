-- corpus 스키마 (03-db-schema §3, ADR-006). 모든 문장은 IF NOT EXISTS 로 여러 번 실행해도 안전하다.
-- 벡터 표(langchain_pg_collection·langchain_pg_embedding)는 PGVector 가 만든다. 여기서 정의하지 않는다(ADR-009).
-- 이미 있는 표의 컬럼·제약 변경은 자동 반영되지 않는다: 청크·판본·이슈 표만 지우고 다시 만든다(원문 표 보존).

CREATE EXTENSION IF NOT EXISTS vector;

-- ENT-01 가져온 원문 (청크·색인을 다시 만들어도 보존)
CREATE TABLE IF NOT EXISTS source_documents (
    doc_id              text        NOT NULL,
    kind                text        NOT NULL,
    title               text        NOT NULL,
    case_number         text,
    decided_on          date,
    court               text,
    case_type           text,
    holdings            text,
    summary             text,
    referenced_articles text,
    law_name            text,
    article_no          integer,
    article_branch_no   integer     DEFAULT 0,
    article_title       text,
    body                text,
    effective_on        date,
    source_file         text        NOT NULL,
    source_line         integer     NOT NULL,
    content_sha         text        NOT NULL,
    imported_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT source_documents_pkey PRIMARY KEY (doc_id),
    CONSTRAINT source_documents_kind_check
        CHECK (kind IN ('STATUTE_ARTICLE', 'PRECEDENT')),
    CONSTRAINT source_documents_precedent_content_check
        CHECK (kind <> 'PRECEDENT'
               OR coalesce(btrim(holdings), '') <> ''
               OR coalesce(btrim(summary), '') <> ''),
    CONSTRAINT source_documents_statute_content_check
        CHECK (kind <> 'STATUTE_ARTICLE'
               OR (body IS NOT NULL AND article_no IS NOT NULL))
);

-- ENT-03 색인 판본
CREATE TABLE IF NOT EXISTS index_versions (
    index_version   text        NOT NULL,
    corpus_version  text        NOT NULL,
    max_chars       integer     NOT NULL,
    overlap_chars   integer     NOT NULL,
    embedding_model text        NOT NULL,
    embedding_dim   integer     NOT NULL,
    doc_count       integer     NOT NULL DEFAULT 0,
    chunk_count     integer     NOT NULL DEFAULT 0,
    skipped_count   integer     NOT NULL DEFAULT 0,
    complete        boolean     NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT index_versions_pkey PRIMARY KEY (index_version),
    CONSTRAINT index_versions_max_chars_check CHECK (max_chars > 0),
    CONSTRAINT index_versions_overlap_chars_check CHECK (overlap_chars >= 0)
);

-- ENT-02 청크
CREATE TABLE IF NOT EXISTS chunks (
    index_version       text        NOT NULL,
    chunk_id            text        NOT NULL,
    doc_id              text        NOT NULL,
    kind                text        NOT NULL,
    section             text        NOT NULL,
    seq                 integer     NOT NULL,
    location            text        NOT NULL,
    text                text        NOT NULL,
    referenced_articles text,
    bm25_tokens         text[]      NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chunks_pkey PRIMARY KEY (index_version, chunk_id),
    CONSTRAINT chunks_index_version_fkey FOREIGN KEY (index_version)
        REFERENCES index_versions (index_version) ON DELETE CASCADE,
    CONSTRAINT chunks_doc_id_fkey FOREIGN KEY (doc_id)
        REFERENCES source_documents (doc_id) ON DELETE RESTRICT,
    CONSTRAINT chunks_kind_check CHECK (kind IN ('STATUTE_ARTICLE', 'PRECEDENT')),
    CONSTRAINT chunks_section_check CHECK (section IN ('ARTICLE', 'HOLDING')),
    CONSTRAINT chunks_seq_check CHECK (seq >= 1),
    CONSTRAINT chunks_text_check CHECK (length(text) > 0)
);

CREATE INDEX IF NOT EXISTS chunks_index_version_doc_id_idx ON chunks (index_version, doc_id);

-- ENT-04 가져오기 문제 기록 — CR-007: 가져오기(SEQ-01)가 색인보다 먼저 실행되므로 corpus_version 으로 묶는다(FK 없음)
CREATE TABLE IF NOT EXISTS import_issues (
    id             bigint      GENERATED ALWAYS AS IDENTITY,
    corpus_version text        NOT NULL,
    source_file    text        NOT NULL,
    source_line    integer     NOT NULL,
    reason         text        NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT import_issues_pkey PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS import_issues_corpus_version_idx ON import_issues (corpus_version);
