-- faq_alias 데이터 적재 예시
-- 전제: docs/db/faq_search_migration.sql 를 적용해 faq_alias 테이블이 존재해야 함.

-- 예시: 출입증(배지) 수령 관련 alias
-- (faq_id 는 kprint_qa_quickmenu.qna_code 를 그대로 사용)
INSERT INTO faq_alias (faq_id, alias_question)
VALUES
  ('kp_visitor_badge_pickup', '출입증 어디서 받아?'),
  ('kp_visitor_badge_pickup', '배지 수령 위치'),
  ('kp_visitor_badge_pickup', '입장 배지 받는곳'),
  ('kp_visitor_badge_pickup', '등록대 위치');

-- 예시: 주차 요금 alias
INSERT INTO faq_alias (faq_id, alias_question)
VALUES
  ('kp_parking_fee', '주차 얼마야?'),
  ('kp_parking_fee', '주차 요금 알려줘'),
  ('kp_parking_fee', '주차비');

-- 운영에서는 CSV로 alias_question을 관리하고 COPY로 적재하는 것을 권장.
-- 예)
-- 1) alias.csv (컬럼: faq_id,alias_question)
-- 2) \copy faq_alias(faq_id, alias_question) FROM 'alias.csv' CSV HEADER;

