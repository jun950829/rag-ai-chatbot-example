# 챗봇 운영 아키텍처 (2 EC2 고정)

## 1) 폴더 구조

```text
rag-ai-chatbot-example/
├── main/                      # EC2-1: API + Front + Redis + PostgreSQL(pgvector)
│   ├── app/
│   │   ├── main.py            # /chat, /stream, /embed, static serving
│   │   ├── config.py          # API 환경설정
│   │   ├── redis_queue.py     # Redis 큐 추상화
│   │   ├── schemas.py         # 요청/응답 스키마
│   │   └── sql/schema.sql     # pgvector 스키마 + 예시 쿼리
│   ├── frontend/dist/         # React build 산출물 위치
│   ├── Dockerfile
│   └── docker-compose.ec2-1.yml
└── embedding/                 # EC2-2: Worker (LLM + embedding batch)
    ├── worker/
    │   ├── main.py            # 단일 워커 프로세스 엔트리
    │   ├── consumers.py       # llm_consumer + embedding_consumer
    │   ├── queue.py           # 워커용 Redis 큐 추상화
    │   ├── llm.py             # LLM 스트림 호출 어댑터
    │   ├── embedding.py       # 배치 임베딩 함수
    │   └── config.py          # 워커 환경설정
    ├── Dockerfile
    └── docker-compose.ec2-2.yml
```

## 2) 핵심 흐름

- **채팅 요청**
  - 사용자 → `POST /chat`
  - API는 Redis 캐시 확인 후 miss 시 `queue:llm` 에 작업 enqueue
  - Worker가 LLM 처리 후 Redis `stream:llm:{request_id}`에 토큰 push
  - API `GET /stream/{request_id}` 가 SSE로 토큰 relay

- **임베딩 요청**
  - 문서 업로드/수정 이벤트 → `POST /embed`
  - API는 `queue:embedding` 에 작업 enqueue
  - Worker가 배치(`EMBED_BATCH_SIZE=32`)로 임베딩 후 pgvector upsert

## 3) 운영 포인트 (100명 규모 최적화)

- API 서버는 CPU 무거운 작업(LLM/임베딩)을 수행하지 않음
- 워커는 BLPOP 기반 큐 소비로 idle 시 자원 사용 최소화
- Redis 캐시로 반복 질문 비용 절감
- 임베딩 배치로 모델 호출 횟수 감소
- SSE로 사용자 체감 응답속도 개선

## 4) 배포

- EC2-1:
  - `cd main && cp .env.example .env`
  - `docker compose -f docker-compose.ec2-1.yml up -d --build`
- EC2-2:
  - `cd embedding && cp .env.example .env`
  - `docker compose -f docker-compose.ec2-2.yml up -d --build`
