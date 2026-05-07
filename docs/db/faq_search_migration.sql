-- FAQ 검색 엔진(FTS + BM25 유사 + pg_trgm + alias)용 스키마/인덱스 권장안
-- 주의: 제품/업체 RAG(pgvector)와 무관. FAQ만 대상.

-- 1) 확장
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2) alias 테이블
CREATE TABLE IF NOT EXISTS faq_alias (
  id bigserial PRIMARY KEY,
  faq_id text NOT NULL, -- kprint_qa_quickmenu.qna_code 를 참조(문자열 코드)
  alias_question text NOT NULL,
  canonical_topic text NULL,
  usage_count bigint NOT NULL DEFAULT 0,
  normalized_question text GENERATED ALWAYS AS (
    regexp_replace(
      regexp_replace(lower(alias_question), '[^0-9a-z가-힣\s]', ' ', 'g'),
      '\s+', ' ', 'g'
    )
  ) STORED,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_faq_alias_faq_id ON faq_alias(faq_id);
CREATE INDEX IF NOT EXISTS idx_faq_alias_trgm ON faq_alias USING GIN (alias_question gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_faq_alias_norm_trgm ON faq_alias USING GIN (normalized_question gin_trgm_ops);

-- 3) kprint_qa_quickmenu: normalized + generated tsvector
ALTER TABLE kprint_qa_quickmenu
  ADD COLUMN IF NOT EXISTS normalized_question text GENERATED ALWAYS AS (
    regexp_replace(
      regexp_replace(lower(coalesce(question_sample,'')), '[^0-9a-z가-힣\s]', ' ', 'g'),
      '\s+', ' ', 'g'
    )
  ) STORED;

ALTER TABLE kprint_qa_quickmenu
  ADD COLUMN IF NOT EXISTS search_vector tsvector GENERATED ALWAYS AS (
    to_tsvector(
      'simple',
      coalesce(question_sample,'') || ' ' ||
      coalesce(quickmenu_label,'') || ' ' ||
      coalesce(category,'') || ' ' ||
      coalesce(subcategory,'') || ' ' ||
      coalesce(domain,'')
    )
  ) STORED;

-- 3-b) FAQ 전용 가중 tsvector (질문/라벨=A, 카테고리=B, 답변=C)
ALTER TABLE kprint_qa_quickmenu
  ADD COLUMN IF NOT EXISTS faq_search_tsv tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('simple', coalesce(question_sample, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(quickmenu_label, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(category, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce(subcategory, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce(answer_sample, '')), 'C')
  ) STORED;

-- 4) 인덱스: FTS + trigram
CREATE INDEX IF NOT EXISTS idx_kprint_qa_quickmenu_search_vector
  ON kprint_qa_quickmenu USING GIN (search_vector);

CREATE INDEX IF NOT EXISTS idx_faq_tsv
  ON kprint_qa_quickmenu USING GIN (faq_search_tsv);

CREATE INDEX IF NOT EXISTS idx_kprint_qa_quickmenu_question_trgm
  ON kprint_qa_quickmenu USING GIN (question_sample gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_faq_label_trgm
  ON kprint_qa_quickmenu USING GIN (quickmenu_label gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_kprint_qa_quickmenu_norm_trgm
  ON kprint_qa_quickmenu USING GIN (normalized_question gin_trgm_ops);

-- 5) qa_user 필터가 많다면(모드별) 부분 인덱스도 고려
-- CREATE INDEX CONCURRENTLY ... WHERE qa_user='visitor' OR qa_user IS NULL OR qa_user='';
-- CREATE INDEX CONCURRENTLY ... WHERE qa_user='exhibitor' OR qa_user IS NULL OR qa_user='';

