# Exmatch AI 배포 및 장애 대응 기록

> 작성일: 2026-05-07 13:23:23 KST  
> 기준 자료: 사용자가 전달한 Codex 대화 복사본  
> 주의: 본 문서에는 서버 IP, 로컬 경로, 배포 경로 등이 포함되어 있으므로 외부 공유 전 민감정보를 확인해야 합니다.

---

## 1. 작업 개요

Exmatch AI 관련 3개 프로젝트를 원격 서버에 배포하고, 이후 발생한 데이터 미노출 및 채팅 전송 문제를 점검한 기록입니다.

| 구분 | 프로젝트 | 로컬 경로 | 배포 서버 | 원격 배포 경로 | 최종 배포 기준 |
|---|---|---|---|---|---|
| 프론트엔드 | `exmatch-template-frontend` | `C:\Users\Momenti\IdeaProjects\exmatch-template-frontend` | 서비스용 웹서버 | `~/exmatch-template-frontend` | `main` 브랜치 |
| 백엔드 | `exmatch-template` | `C:\Users\Momenti\IdeaProjects\exmatch-template` | 서비스용 웹서버 | `~/exmatch-template` | `main` 브랜치 |
| 임베딩 서버 | `qwen` | `C:\Users\Momenti\Downloads\qwen` | LLM용 웹서버 | `~/qwen` | `benchmark` 브랜치 |

---

## 2. 서버 정보

| 구분 | IP | 계정 | 비고 |
|---|---:|---|---|
| 서비스용 웹서버 | `52.64.112.27` | `exmatch2604` | 프론트엔드/백엔드 배포 |
| LLM용 웹서버 | `15.135.211.14` | `exmatch2604` | Qwen 임베딩 서버 배포 |

PEM 키 경로는 로컬 기준 다음 경로로 전달되었습니다.

```text
C:\Users\Momenti\Downloads\exmatch-publickey (1).pem
```

---

## 3. 최종 접속 URL

| 항목 | URL | 상태 |
|---|---|---|
| 프론트엔드 | `http://52.64.112.27:3000` | 컨테이너 기동 확인 |
| API health | `http://52.64.112.27/api/v1/health` | 정상 확인 |
| API direct health | `http://52.64.112.27:8000/api/v1/health` | 초반 검증에 사용 |
| Qwen health | `http://15.135.211.14:4022/health` | `ready=true` 확인 |

백엔드는 최종적으로 웹서버 내부에서 LLM 서버의 공인 IP가 아니라 내부 IP로 접근하도록 설정되었습니다.

```text
EMBED_API_URL=http://10.0.30.118:4022
```

---

## 4. 최종 배포 기준

초기에는 로컬 작업 브랜치 기준으로 배포되어 있었고, 이후 사용자가 기준을 정정했습니다.

| 대상 | 초기 배포 기준 | 최종 배포 기준 | 비고 |
|---|---|---|---|
| 백엔드 | `seunghak` 브랜치, commit `70eca4d` | `main`, commit `7aad9e1` | main 기준 재배포 |
| 프론트엔드 | `seunghak` 브랜치, commit `c15fe65` | `main`, commit `c558fa9` | main 기준 재배포 |
| qwen | `benchmark`, commit `36f60ca` | `benchmark`, commit `36f60ca` | 유지 |

qwen의 경우 `main` 브랜치는 `Qwen3-Embedding-4B` 및 Apple M4/MPS 최적화 코드가 포함되어 있어, 현재 LLM EC2 CPU 서버에는 부적합하다고 판단되어 `benchmark` 브랜치 배포를 유지했습니다.

---

## 5. 배포 과정 요약

### 5.1 PEM 키 권한 이슈

Windows OpenSSH에서 PEM 키 권한이 너무 공개적이라고 판단하여 SSH 접속이 거부되었습니다.

진행 중 확인된 내용은 다음과 같습니다.

- `Downloads` 위치의 ACL 때문에 SSH가 PEM 키를 거부함
- `.deploy` 폴더로 키 복사를 시도했으나 권한 문제로 실패
- 원본 키의 ACL이 꼬여 읽기 권한이 사라짐
- `Momenti` 사용자에게 읽기 권한을 다시 부여
- `CodexSandboxOffline` 사용자 권한이 남아 있어 OpenSSH가 다시 거부
- 최종적으로 원본 키에서 불필요한 권한을 제거하고 `Momenti` 사용자 기준으로 접속 성공

### 5.2 원격 서버 상태 확인

두 서버 모두 기존 `~/rag-ai-chatbot-example` 디렉터리가 있었습니다. 기존 구조와 이번 로컬 프로젝트 구조가 달라서 섞지 않고 별도 경로에 배포하기로 했습니다.

| 서버 | 확인 결과 | 결정 |
|---|---|---|
| 웹서버 | Docker 있음, Node 없음 | 프론트/백엔드 모두 Docker 기반 배포 |
| LLM 서버 | Python 있음, pip 없음, 디스크 여유 약 1.5GB | 기존 embedding `.venv` 재사용 |

LLM 서버에는 기존 경로에 `sentence_transformers`, CPU Torch가 설치된 가상환경이 있었기 때문에 새로 무거운 Qwen/Torch 이미지를 빌드하지 않고 기존 가상환경을 재사용했습니다.

```text
~/rag-ai-chatbot-example/embedding/.venv
```

### 5.3 압축 및 전송

로컬에서 각 프로젝트를 tar.gz로 묶어 서버로 전송했습니다.

```powershell
New-Item -ItemType Directory -Force -Path .deploy | Out-Null

tar --exclude='.git' --exclude='.deploy' --exclude='logs' --exclude='__pycache__' --exclude='.pytest_cache' \
  -czf .deploy\backend.tar.gz \
  -C C:\Users\Momenti\IdeaProjects\exmatch-template .

tar --exclude='.git' --exclude='node_modules' --exclude='.next' --exclude='frontend-3000*.log' --exclude='next-start*.log' \
  -czf .deploy\frontend.tar.gz \
  -C C:\Users\Momenti\IdeaProjects\exmatch-template-frontend .

tar --exclude='.git' --exclude='lang' --exclude='__pycache__' --exclude='benchmark_data' \
  -czf .deploy\qwen.tar.gz \
  -C C:\Users\Momenti\Downloads\qwen qwen
```

### 5.4 Qwen 임베딩 서버 배포

LLM 서버에서 qwen 프로젝트를 `~/qwen`에 풀고 기존 가상환경으로 실행했습니다.

```bash
cd ~/qwen
nohup ~/rag-ai-chatbot-example/embedding/.venv/bin/python main.py \
  > embedding-4022.out.log \
  2> embedding-4022.err.log &
```

초기 실행 명령은 모델 로딩 시간이 길어져 Codex 실행 제한에 걸렸으나, 백그라운드 프로세스는 살아 있었고 이후 health 체크에서 정상 확인되었습니다.

```text
http://15.135.211.14:4022/health
ready=true
```

재부팅 후 자동 실행을 위해 LLM 서버에 `start_qwen.sh`와 `crontab @reboot` 등록도 진행했습니다.

### 5.5 백엔드/프론트 Docker 배포

웹서버에는 다음 경로로 소스를 배치했습니다.

```text
~/exmatch-template
~/exmatch-template-frontend
```

백엔드는 Docker Compose로 기동했습니다.

```bash
cd ~/exmatch-template
docker compose up -d --build
```

프론트도 Docker 기반으로 빌드/기동했습니다.

```bash
cd ~/exmatch-template-frontend
docker compose up -d --build
```

---

## 6. 주요 문제와 해결 내용

### 6.1 `docker/entrypoint.sh` 실행 권한 문제

백엔드 컨테이너 시작 시 `docker/entrypoint.sh` 실행 권한 문제로 막혔습니다. Windows에서 압축/복사되며 실행 비트가 사라진 것으로 판단되었습니다.

해결 방향:

```Dockerfile
sh ./docker/entrypoint.sh
```

즉, Dockerfile에서 entrypoint 파일을 직접 실행하는 대신 `sh`로 실행하도록 변경했습니다.

### 6.2 웹서버에서 LLM 공인 IP 접근 타임아웃

외부에서는 `15.135.211.14:4022` health가 열렸지만, 웹서버 내부에서 해당 공인 IP로 접근하면 타임아웃이 발생했습니다.

확인 결과 LLM 서버의 내부 IP는 다음과 같았습니다.

```text
10.0.30.118
```

웹서버에서 내부 IP로 접근하면 정상 동작했기 때문에 백엔드 `.env`를 다음처럼 변경했습니다.

```env
EMBED_API_URL=http://10.0.30.118:4022
```

### 6.3 원격 DB 데이터 없음 문제

초기 원격 DB는 마이그레이션만 되어 있고 실제 데이터가 비어 있었습니다. 따라서 화면에서 상품/FAQ가 나오려면 로컬 `rag_template` 데이터를 원격 DB로 복원해야 했습니다.

이후 로컬 DB dump를 원격에 복원했고, 다음 데이터가 존재하는 것으로 확인되었습니다.

| 테이블/항목 | 건수 |
|---|---:|
| `company` | 234 |
| `product` | 421 |
| `faq_item` | 199 |
| product embedding | 2067 |
| faq embedding | 199 |

### 6.4 최초 배포 브랜치 불일치

사용자가 “각각 main 브랜치 코드가 배포된 것이 맞냐”고 확인했고, 실제 확인 결과 초기 배포는 main이 아니었습니다.

초기 상태:

```text
백엔드: seunghak, 70eca4d
프론트: seunghak, c15fe65
qwen: benchmark, 36f60ca
```

이후 사용자가 기준을 명확히 했습니다.

```text
백엔드/프론트: main 브랜치 배포
qwen: benchmark 브랜치 배포 유지
```

이에 따라 백엔드/프론트는 `git archive main` 방식으로 main 소스만 다시 패키징해서 배포했습니다.

### 6.5 main 코드와 기존 DB 스키마 불일치

백엔드 main 코드는 기존 DB와 다른 스키마를 기대했습니다. 대표적으로 다음 문제가 있었습니다.

- main 코드는 `*_embedding_1024` 테이블을 찾음
- 기존 복원 DB에는 `product_profile_embedding`, `company_profile_embedding` 등 suffix 없는 테이블이 존재
- 기존 Alembic 버전 `0006`과 main 마이그레이션 그래프가 맞지 않음
- main 기준 채팅 테이블 컬럼명이 기존 DB와 다름
- `event`, `chat_session`, `event_slug`, `cards_json`, `state_json` 등의 호환 필요

운영 데이터를 날리지 않기 위해 자동 마이그레이션을 끄고 호환 테이블/컬럼을 추가하는 방식으로 대응했습니다.

```env
RUN_MIGRATIONS=0
```

추가로 생성한 호환 SQL 파일:

```text
.deploy/main_embedding_compat.sql
.deploy/main_schema_compat.sql
```

호환 처리 예시:

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE company_profile_embedding_1024 AS
SELECT
  company_id,
  content AS profile_text,
  content_hash::text AS content_hash,
  embedding,
  'Qwen/Qwen3-Embedding-0.6B'::text AS embedding_model,
  'legacy-import'::text AS template_version,
  created_at AS indexed_at,
  updated_at AS updated_at
FROM company_profile_embedding;
```

### 6.6 main 검색 SQL의 `event_slug` 타입 캐스팅 문제

스모크 테스트 중 thread 생성 이후 검색 스트림에서 500 오류가 발생했습니다.

원인은 `:event_slug IS NULL` 형태의 파라미터에 대해 psycopg가 타입을 추론하지 못하는 문제였습니다.

대응:

- main 검색 SQL에 `event_slug` 파라미터를 `text`로 캐스팅하는 런타임 패치 적용
- API 이미지를 다시 빌드

이후 스모크 테스트 통과:

```text
라벨 프린터 제품 보여줘
→ 실제 제품 5개 반환 확인
```

### 6.7 프론트 채팅 화면 메시지 누적 문제

사용자 화면에서 “참관객 FAQ / 참가업체 FAQ / 제품·기업 검색” 같은 초기 메시지가 계속 쌓이는 문제가 있었습니다.

서버 로그상 사용자의 `참가업체 추천해줘` 문장은 백엔드까지 도달하지 않았고, 대신 모드 변경 API만 반복 호출되는 상황이었습니다.

1차 수정:

- 같은 모드 버튼을 다시 눌러도 서버에 모드 변경 요청을 보내지 않도록 수정
- 프론트가 자체 FAQ 인사 메시지를 중복으로 붙이는 로직 제거
- Zustand hydration 체크를 optional API 방식으로 안전하게 변경
- 저장소 키를 `chat-storage-v2`로 변경하여 기존 꼬인 로컬 상태 무시

2차 수정:

- 전송 버튼을 `form submit` 의존이 아니라 명시적 `onClick` 전송으로 변경
- 한글 IME 입력 중 Enter 처리 꼬임 방지
- 저장소 키를 다시 `chat-storage-v3`로 변경
- 프론트 재빌드/재시작

수정된 것으로 언급된 파일/영역:

```text
src/views/home/home.view.tsx
src/views/home/components/chat-input.tsx
```

---

## 7. 검증 결과

### 7.1 백엔드/DB/임베딩 검증

백엔드에서 직접 스모크 테스트를 실행했을 때 정상 동작이 확인되었습니다.

검증 문장 예시:

```text
라벨 프린터 제품 보여줘
참가업체 추천해줘
```

확인 결과:

- 원격 백엔드 요청 정상
- 원격 DB 조회 정상
- LLM 서버 임베딩 호출 정상
- 제품/참가업체 결과 반환 정상

### 7.2 브라우저 화면 기준 남은 문제

사용자 캡처 기준으로는 입력창에 `참가업체 추천해줘`가 남아 있었고, 백엔드 로그에도 해당 문장이 들어오지 않았습니다.

따라서 이 시점의 판단은 다음과 같습니다.

> 검색 결과가 비어 있는 문제가 아니라, 사용자 브라우저에서 입력 전송 이벤트가 실행되지 않는 문제에 가깝습니다.

가능성이 있는 원인:

1. 브라우저가 이전 JS 번들을 캐싱하고 있음
2. `localhost:3000`을 보고 있어 원격 배포본이 아닌 로컬 프론트를 보고 있음
3. 프론트 저장소 상태가 꼬여 이전 thread/session 상태를 계속 복원함
4. 전송 버튼 또는 Enter 이벤트가 특정 화면 상태에서 막힘
5. 프론트에서 API 요청 자체가 발생하지 않음

---

## 8. 현재 기준 다음 확인 사항

아래 순서로 확인하는 것이 좋습니다.

### 8.1 사용자가 보고 있는 주소 확인

브라우저 주소가 반드시 아래인지 확인합니다.

```text
http://52.64.112.27:3000
```

`localhost:3000`을 보고 있다면 원격 배포본이 아니라 로컬 프론트일 수 있습니다.

### 8.2 브라우저 캐시/스토리지 초기화

강력 새로고침:

```text
Ctrl + F5
```

그래도 안 되면 개발자 도구에서 Application 탭 기준으로 다음 항목 삭제를 권장합니다.

```text
Local Storage
Session Storage
IndexedDB
Cache Storage
```

특히 아래 키와 관련된 저장소를 확인합니다.

```text
chat-storage
chat-storage-v2
chat-storage-v3
```

### 8.3 Network 탭 확인

`참가업체 추천해줘` 입력 후 빨간 전송 버튼 클릭 시, Network 탭에 다음과 유사한 요청이 발생해야 합니다.

```text
POST /api/v1/chat/threads/{threadId}/messages/stream
```

요청 자체가 없다면 프론트 이벤트 문제입니다.
요청이 4xx/5xx라면 백엔드/API 문제입니다.
요청이 200인데 화면에 안 나오면 SSE 렌더링 문제입니다.

### 8.4 서버 로그 확인

웹서버에서 API 로그 확인:

```bash
cd ~/exmatch-template
docker compose logs -f api
```

프론트 로그 확인:

```bash
cd ~/exmatch-template-frontend
docker compose logs -f frontend
```

컨테이너 상태 확인:

```bash
docker ps
```

---

## 9. 배포 중 생성/수정된 파일

로컬 또는 `.deploy`에 생성/수정된 것으로 언급된 파일입니다.

```text
.gitignore
Dockerfile
.deploy/smoke_remote.sh
.deploy/smoke_main.py
.deploy/main_embedding_compat.sql
.deploy/main_schema_compat.sql
.deploy/smoke_company.py
.deploy/frontend-main.Dockerfile
.deploy/frontend-main.compose.yml
.deploy/frontend-main.dockerignore
.deploy/backend.override.yml
.deploy/deploy_main_web.sh
```

프론트 수정 관련으로 언급된 파일:

```text
src/views/home/home.view.tsx
src/views/home/components/chat-input.tsx
```

---

## 10. 최종 상태 정리

| 항목 | 상태 |
|---|---|
| 백엔드 main 배포 | 완료 |
| 프론트 main 배포 | 완료 |
| qwen benchmark 배포 | 유지 |
| Qwen health | 정상 |
| API health | 정상 |
| DB 데이터 | 존재 확인 |
| 백엔드 스모크 테스트 | 정상 |
| 브라우저 채팅 전송 | 사용자 화면 기준 미해결 가능성 있음 |

현재까지의 가장 중요한 결론은 다음입니다.

> 백엔드/DB/임베딩은 서버 스모크 테스트 기준 정상입니다. 다만 사용자 화면에서는 `참가업체 추천해줘` 요청이 백엔드로 도달하지 않아, 브라우저 캐시/스토리지 또는 프론트 전송 이벤트 쪽을 추가 확인해야 합니다.

---

## 11. 다음 작업 제안

1. 원격 프론트 주소에서 확인 중인지 먼저 확인
2. 브라우저 저장소와 캐시 완전 삭제
3. Network 탭에서 `messages/stream` 요청 발생 여부 확인
4. 요청이 없으면 `chat-input.tsx`의 전송 핸들러를 다시 확인
5. 요청은 있는데 화면 미출력이면 SSE 스트림 파싱/렌더링 로직 확인
6. 요청이 500이면 API 로그 기준으로 백엔드 오류 확인

---

## 12. 원본 대화 전문

아래는 사용자가 전달한 대화 복사본 원문입니다.

<details>
<summary>원본 대화 펼치기</summary>

`````text
"C:\Users\Momenti\IdeaProjects\exmatch-template-frontend"이 프론트 코드와, "C:\Users\Momenti\IdeaProjects\exmatch-template"이 백엔드 코드와, "C:\Users\Momenti\Downloads\qwen" 이 임베딩 서버를 원격서버에 배포할거야. 
접속정보 (pem파일은 DM으로 전달드립니다.)
서비스용 웹서버
IP: 52.64.112.27
user: exmatch2604
LLM용 웹서버
IP: 15.135.211.14
user: exmatch2604

프론트 코드랑 백엔드 코드는 웹서버에 배포할거고, qwen 프로젝트 코드는 llm 서버에 배포할거야. 
"C:\Users\Momenti\Downloads\exmatch-publickey (1).pem" 이게 서버 접속 팸키야.
오전 10:47


이전 메시지 132개
좋아요. 배포 작업으로 이해했습니다. 먼저 로컬 세 프로젝트의 상태와 PEM 키 권한, 두 원격 서버 접속 가능 여부를 확인한 뒤, 서버에 이미 어떤 컨테이너/디렉터리가 있는지 보고 기존 방식에 맞춰 올리겠습니다.


명령어 4개 실행
로컬 경로와 키 파일은 확인됐습니다. 이제 키 권한을 SSH가 받아들이는 형태로 정리하고, 웹서버/LLM서버에 접속해서 Docker와 기존 배포 디렉터리를 확인하겠습니다.


명령어 3개 실행
키 파일 권한이 아직 SSH 기준으로 막혀 있습니다. 방금 icacls에서 /grant:r 인자 조합이 깨져서 읽기 권한 부여가 안 된 상태라, 현재 계정명을 직접 확인해서 다시 권한을 잡겠습니다.


명령어 8개 실행
파일 내용은 읽히는데 Windows OpenSSH가 Downloads 위치의 ACL을 계속 거부하고 있습니다. 배포용으로 프로젝트의 .deploy 폴더에 키를 복사한 뒤, 그 복사본의 ACL을 단순하게 잡아서 SSH에 사용하겠습니다. 원본 키는 그대로 둡니다.


명령어 2개 실행
복사 명령은 권한상 거부됐지만 파일 읽기는 가능했습니다. 키가 Git에 섞이지 않도록 먼저 .gitignore에 .deploy/와 *.pem을 추가하고, 읽기/쓰기 방식으로 안전한 복사본을 만들겠습니다.


파일 1개 수정,명령어 2개 실행함
방금 원본 ACL이 꼬이면서 읽기가 다시 막혔고, 복사본은 빈 파일로 만들어졌습니다. 빈 복사본은 쓰지 않고, 원본 키 ACL을 먼저 복구해서 다시 읽을 수 있게 만든 뒤 진행하겠습니다.


명령어 12개 실행
원인이 두 겹이었습니다: 샌드박스 안에서는 네트워크가 막히고, 승인 실행 쪽에서는 원본 키가 Momenti 사용자 권한을 잃어서 못 읽는 상태입니다. 원본 키에 Momenti 읽기 권한도 다시 붙인 뒤 승인 실행 SSH로 접속하겠습니다.


명령어 3개 실행
이제 SSH가 키를 읽긴 하는데, Windows OpenSSH가 “CodexSandboxOffline에도 읽기 권한이 있어서 너무 공개적”이라고 거부합니다. 배포 SSH는 승인 실행 사용자 기준으로만 쓰면 되니, 원본 키에서 Codex 권한을 빼고 Momenti만 읽게 정리하겠습니다.


명령어 3개 실행
두 서버 접속은 성공했습니다. 양쪽 모두 기존 ~/rag-ai-chatbot-example 디렉터리가 있어서, 그 안의 구성과 실행 방식을 확인한 다음 기존 배포를 덮어쓰기보다는 새 배포 디렉터리/compose 방식으로 정리해서 올리겠습니다.


명령어 4개 실행
기존 원격 디렉터리는 이전 rag-ai-chatbot-example 구조라 지금 로컬 프로젝트와 다릅니다. 섞지 않고 새 배포 경로를 만들겠습니다: 웹서버에는 ~/exmatch-template와 ~/exmatch-template-frontend, LLM 서버에는 ~/qwen. 먼저 서버 런타임(Node/Docker/Python) 상태를 확인하겠습니다.


명령어 4개 실행
웹서버는 Docker는 있고 Node는 없습니다. 그래서 프론트도 Docker 컨테이너로 배포해야 합니다. LLM 서버는 Python은 있지만 pip가 없고 디스크가 1.5GB만 남아 있어서, Qwen/Torch 이미지를 새로 빌드하기엔 공간이 빡빡합니다. 먼저 LLM 서버에 이미 임베딩용 가상환경/모델 캐시가 있는지 확인해서 가장 덜 무거운 방식으로 올리겠습니다.


명령어 9개 실행
좋은 단서가 나왔습니다. LLM 서버의 기존 embedding/.venv에는 sentence_transformers와 CPU Torch가 이미 설치되어 있어서, Qwen 코드는 그 가상환경을 재사용하면 됩니다. 웹서버는 Docker 기반으로 백엔드/프론트를 올리고, 프론트 Dockerfile은 원격에 생성해서 빌드하겠습니다.

New-Item -ItemType Directory -Force -Path .deploy | Out-Null; tar --exclude='.git' --exclude='.deploy' --exclude='logs' --exclude='__pycache__' --exclude='.pytest_cache' -czf .deploy\backend.tar.gz -C C:\Users\Momenti\IdeaProjects\exmatch-template .; tar --exclude='.git' --exclude='node_modules' --exclude='.next' --exclude='frontend-3000*.log' --exclude='next-start*.log' -czf .deploy\frontend.tar.gz -C C:\Users\Momenti\IdeaProjects\exmatch-template-frontend .; tar --exclude='.git' --exclude='lang' --exclude='__pycache__' --exclude='benchmark_data' -czf .deploy\qwen.tar.gz -C C:\Users\Momenti\Downloads\qwen qwen; Get-ChildItem .deploy\*.tar.gz | Select-Object Name,Length 실행함
배포 아카이브를 만들었습니다. 이제 웹서버로 백엔드/프론트, LLM 서버로 qwen 아카이브를 전송하겠습니다.


명령어 3개 실행
전송은 끝났습니다. 먼저 LLM 서버에서 ~/qwen을 풀고 기존 embedding 가상환경으로 4022 포트 서비스를 띄우겠습니다. 그 다음 웹서버에서 백엔드/프론트 Docker 배포로 넘어가겠습니다.

ssh -i 'C:\Users\Momenti\Downloads\exmatch-publickey (1).pem' -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL exmatch2604@15.135.211.14 'set -e; rm -rf ~/qwen; tar -xzf ~/qwen.tar.gz -C ~; mv ~/qwen/qwen/* ~/qwen/ 2>/dev/null || true; rmdir ~/qwen/qwen 2>/dev/null || true; pkill -f "/home/exmatch2604/qwen/main.py" 2>/dev/null || true; cd ~/qwen; nohup ~/rag-ai-chatbot-example/embedding/.venv/bin/python main.py > embedding-4022.out.log 2> embedding-4022.err.log & echo $! > embedding-4022.pid; sleep 5; cat embedding-4022.pid; tail -40 embedding-4022.out.log; tail -40 embedding-4022.err.log; curl -fsS http://127.0.0.1:4022/health' 실행함
LLM 서버 시작 명령이 중간에서 실패했는데 출력이 거의 없었습니다. 압축 해제 경로나 set -e에서 멈춘 것 같으니 단계별로 확인해서 이어가겠습니다.


명령어 2개 실행
LLM 서버 시작 명령은 모델 로딩 중이라 120초 제한에 걸렸습니다. 백그라운드 프로세스는 계속 살아 있을 수 있으니 상태를 확인하겠습니다.


명령어 2개 실행
LLM 서버는 http://15.135.211.14:4022/health 기준 ready=true로 올라왔습니다. 이제 웹서버 쪽에 백엔드/프론트 소스를 풀고, 백엔드는 8000, 프론트는 3000 포트로 Docker 배포하겠습니다.


명령어 3개 실행
웹서버 압축 해제는 진행됐고, .env 수정 단계에서 heredoc quoting이 깨져 멈췄습니다. 원격 셸 함수 방식으로 환경값만 다시 안전하게 수정하고 바로 빌드/기동하겠습니다.

ssh -i 'C:\Users\Momenti\Downloads\exmatch-publickey (1).pem' -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL exmatch2604@52.64.112.27 'set -e; cd ~/exmatch-template; set_kv(){ k="$1"; v="$2"; if grep -q "^${k}=" .env; then sed -i "s|^${k}=.*|${k}=${v}|" .env; else printf "%s=%s\n" "$k" "$v" >> .env; fi; }; set_kv APP_ENV production; set_kv APP_RELOAD 0; set_kv RUN_MIGRATIONS 1; set_kv EMBED_API_URL http://15.135.211.14:4022; set_kv CORS_ORIGINS http://52.64.112.27:3000,http://localhost:3000,http://127.0.0.1:3000; sed -n "1,90p" .env | sed -E "s/(KEY|PASSWORD|TOKEN|SECRET)=.*/\1=***REDACTED***/g"; echo --- frontend; ls -la ~/exmatch-template-frontend | head' 실행함
원격 한 줄 명령은 PowerShell/SSH quoting 때문에 계속 깨지고 있습니다. 배포 스크립트를 파일로 만들어 웹서버에 전송한 뒤 bash deploy_web.sh로 실행하겠습니다. 이쪽이 훨씬 안정적입니다.


명령어 5개 실행
웹서버 배포 디렉터리는 준비됐습니다. 이제 백엔드부터 Docker build/up으로 올리고 health를 확인한 다음, 프론트 Docker build/up으로 넘어가겠습니다.

ssh -i 'C:\Users\Momenti\Downloads\exmatch-publickey (1).pem' -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL exmatch2604@52.64.112.27 'set -e; cd ~/exmatch-template; docker compose up -d --build; sleep 8; docker ps --format "{{.Names}}|{{.Image}}|{{.Ports}}"; curl -fsS http://127.0.0.1:8000/api/v1/health' 실행함
백엔드 빌드는 성공했는데 컨테이너 시작에서 docker/entrypoint.sh 실행 권한 때문에 막혔습니다. Windows에서 압축/복사되며 실행 비트가 안 붙은 케이스라, Dockerfile이 sh ./docker/entrypoint.sh로 실행하도록 고치고 다시 빌드하겠습니다.


파일 1개 수정,명령어 1개 실행함
백엔드는 수정 후 정상 기동했고 health가 ok/db ok/redis ok로 확인됐습니다. 이제 프론트 컨테이너를 3000 포트로 빌드/기동하겠습니다.

ssh -i 'C:\Users\Momenti\Downloads\exmatch-publickey (1).pem' -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL exmatch2604@52.64.112.27 'set -e; cd ~/exmatch-template-frontend; docker compose up -d --build; sleep 8; curl -fsS http://127.0.0.1:3000 | head -c 120' 실행함
프론트 컨테이너도 빌드/기동됐고 서버 내부에서 3000 응답 HTML까지 확인됐습니다. 이제 외부에서 접근되는지 세 포트를 직접 확인하고, 백엔드가 LLM 서버의 임베딩 health를 볼 수 있는지도 확인하겠습니다.


명령어 3개 실행
외부에서 세 URL은 모두 응답하지만, 웹서버 내부에서 15.135.211.14:4022로 나가는 호출이 타임아웃됐습니다. 같은 VPC 내부 IP로 붙어야 할 가능성이 높습니다. LLM 서버 hostname이 ip-10-0-30-118이므로 웹서버에서 10.0.30.118:4022 접근을 테스트하고, 되면 백엔드 EMBED_API_URL을 내부 IP로 바꾸겠습니다.


명령어 2개 실행
확인됐습니다. 웹서버에서 LLM 공인 IP는 타임아웃이고, 내부 IP 10.0.30.118:4022는 정상입니다. 백엔드 환경의 EMBED_API_URL을 내부 IP로 바꾸고 API 컨테이너만 재기동하겠습니다.


명령어 2개 실행
백엔드 재기동 후 health와 웹서버→LLM 내부 IP 연결은 둘 다 정상입니다. 스크립트 마지막 줄 CRLF 때문에 exit code만 1로 잡혔지만 실제 변경/재기동/검증은 완료됐습니다. 이제 원격 DB 마이그레이션과 데이터 상태를 확인하겠습니다.


명령어 4개 실행
원격 DB는 마이그레이션만 되어 있고 데이터가 비어 있습니다. 화면에서 실제 상품/FAQ가 뜨려면 로컬 rag_template 데이터를 원격 DB로 복원해야 합니다. 원격은 현재 비어 있으니, 백업 파일 하나 남기고 로컬 DB dump를 올려 복원하겠습니다.


명령어 4개 실행
원격 DB도 로컬 데이터로 복원됐습니다. 이제 마지막으로 프론트 번들에 API 주소가 원격 백엔드로 박혔는지 확인하고, 백엔드 채팅 API가 실제 DB/임베딩 서버까지 타는지 짧은 요청으로 검증하겠습니다.


명령어 2개 실행
마지막 검증 명령도 quoting이 깨졌습니다. 짧은 smoke test 스크립트로 바꿔서 실행하겠습니다.

$script = @' #!/usr/bin/env bash set -euo pipefail echo frontend_status curl -fsS http://127.0.0.1:3000 >/tmp/frontend.html wc -c /tmp/frontend.html echo backend_health curl -fsS http://127.0.0.1:8000/api/v1/health echo echo create_thread thread=$(curl -fsS -X POST http://127.0.0.1:8000/api/v1/chat/threads \ -H 'Content-Type: application/json' \ -d '{"event_slug":"kprint-2025","event_year":2025,"session_mode":"catalog"}' \ | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"]["thread_id"])') echo "$thread" echo stream_tail curl -m 60 -fsS -N -X POST "http://127.0.0.1:8000/api/v1/chat/threads/${thread}/messages/stream" \ -H 'Content-Type: application/json' \ -d '{"message":"라벨 프린터 제품 보여줘","top_k":3}' \ | tail -20 '@ [System.IO.File]::WriteAllText((Resolve-Path .deploy).Path + '\smoke_remote.sh', $script.Replace("`r`n","`n"), [System.Text.UTF8Encoding]::new($false)) scp -i 'C:\Users\Momenti\Downloads\exmatch-publickey (1).pem' -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL .deploy\smoke_remote.sh exmatch2604@52.64.112.27:/home/exmatch2604/smoke_remote.sh; ssh -i 'C:\Users\Momenti\Downloads\exmatch-publickey (1).pem' -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL exmatch2604@52.64.112.27 'bash ~/smoke_remote.sh' 실행함
검색 스트림까지 정상입니다: 원격 백엔드가 원격 DB와 LLM 서버 임베딩을 타고 제품 결과를 반환했습니다. 마지막으로 프론트 번들 안의 API endpoint가 localhost로 잘못 박혀 있지 않은지만 확인하겠습니다.


명령어 3개 실행
현재 프론트 컨테이너 환경값도 http://52.64.112.27:8000/api/v1로 맞습니다. 한 가지 남은 운영상 아쉬움은 qwen이 Docker가 아니라 기존 venv로 nohup 실행 중이라는 점입니다. 서버 재부팅 후에도 살아나도록 LLM 서버에 start_qwen.sh와 crontab @reboot을 걸 수 있는지 확인하겠습니다.


명령어 3개 실행
배포 완료했습니다.

접속 URL:

프론트: 
http://52.64.112.27:3000
백엔드 health: 
http://52.64.112.27:8000/api/v1/health
임베딩 health: 
http://15.135.211.14:4022/health
배포 상태:

웹서버 52.64.112.27

백엔드: ~/exmatch-template
프론트: ~/exmatch-template-frontend
Docker 컨테이너 기동 완료
백엔드 DB도 로컬 rag_template 데이터로 복원 완료
LLM 서버 15.135.211.14

qwen: ~/qwen
기존 rag-ai-chatbot-example/embedding/.venv 재사용
4022 포트로 실행 완료

start_qwen.sh
 crontab 등록 완료
검증도 했습니다. 원격 백엔드에서 라벨 프린터 제품 보여줘로 실제 스트리밍 검색 요청을 날렸고, DB/임베딩까지 타서 제품 9개 결과가 정상 반환됐습니다.

로컬 코드에는 배포 과정에서 Dockerfile과 .gitignore가 변경됐습니다. Dockerfile은 서버에서 entrypoint 실행 권한 문제를 피하려고 sh ./docker/entrypoint.sh 방식으로 바꿨고, .gitignore에는 .deploy/, *.pem을 추가했습니다.

2개 파일 변경됨
+9
-7
실행 취소
리뷰

.gitignore
Dockerfile




오전 11:17
"C:\Users\Momenti\Downloads\데이터 없음.png"이 사진 보면 알겠지만 데이터가 없는데? 그리고 해당 프로젝트들의 각각 main 브랜치에 있는 코드 배포된거 맞아?
오전 11:18


이전 메시지 24개
먼저 스크린샷을 확인하고, 세 프로젝트가 실제로 어떤 브랜치 상태에서 패키징됐는지 로컬 git 기준과 원격 배포 디렉터리 기준을 같이 확인하겠습니다. “데이터 없음”은 DB가 비었거나, 프론트가 다른 API를 보고 있거나, 메인 브랜치 코드가 아닌 코드가 올라간 경우 셋 중 하나일 가능성이 큽니다.




명령어 4개 실행
확인해보니 중요한 부분이 하나 바로 나왔습니다. 어제 배포한 건 main 브랜치가 아니라 로컬 seunghak 브랜치 작업물입니다. 백엔드도 seunghak, 프론트도 seunghak 상태에서 패키징됐습니다. 이제 “데이터 없음”이 실제 API 문제인지, 프론트 동작/브라우저 상태 문제인지 원격 API와 화면 흐름을 직접 찔러보겠습니다.


명령어 4개 실행
원격 POST /chat/threads는 정상이고 DB도 어제 복원했는데, 생성된 thread의 messages가 빈 배열입니다. 현재 프론트는 버튼 선택 전에는 원래 빈 화면처럼 보일 수 있고, FAQ intro 문구는 프론트 로컬 상태로 붙는 구조입니다. 다만 브랜치 문제는 확실합니다: 지금 배포본은 main이 아닙니다. 백엔드/프론트는 seunghak, qwen은 benchmark 기반입니다. main 배포가 맞아야 한다면 지금 main 기준으로 다시 패키징해서 올리겠습니다.


명령어 3개 실행
main 브랜치 내용을 확인했는데, 그대로 배포하면 오히려 위험한 부분이 있습니다. 특히 qwen main은 기본 모델이 Qwen3-Embedding-4B이고 Apple M4/MPS 최적화 코드라 LLM EC2 CPU 서버에는 부적합합니다. 지금 서버에서 정상 동작 중인 건 benchmark 브랜치의 0.6B CPU용 코드입니다. 백엔드 main도 compose 구조가 지금 배포한 8000 직접 노출 구조와 다릅니다. 그래서 “main 그대로”를 원하면 가능은 하지만, 현재 정상 검색되는 배포가 깨질 수 있어요. 우선 데이터 없음 화면 원인을 더 좁히겠습니다.

Get-Content C:\Users\Momenti\.codex\plugins\cache\openai-bundled\browser-use\0.1.0-alpha1\skills\browser\SKILL.md 실행함
Node Repl 사용
브라우저 플러그인으로 직접 클릭 테스트를 하려 했는데, 현재 내장 Node 런타임이 v20.16.0이라 브라우저 자동화 플러그인이 요구하는 v22.22.0+ 조건을 못 맞춰 실행이 안 됩니다. 대신 코드와 API 기준으로 확인하면, 스크린샷의 “버튼 3개만 보이는 화면”은 현재 프론트의 초기 화면 동작과 일치합니다. 실제 데이터는 버튼 선택 후 API 호출/질문 입력 시 로드되는 구조입니다. 계속 원격 API와 프론트 코드 기준으로 원인을 잡겠습니다.


명령어 5개 실행
아니요. 정확히 말하면 각 프로젝트의 main 브랜치 코드가 배포된 상태는 아닙니다.

현재 배포 기준은:

백엔드: 로컬 seunghak 브랜치, commit 70eca4d
프론트: 로컬 seunghak 브랜치, commit c15fe65
qwen: 로컬 benchmark 브랜치, commit 36f60ca + main.py 수정본 포함
그리고 “데이터 없음”처럼 보이는 건 DB가 비어 있어서가 아닙니다. 원격 DB에는 데이터가 있습니다:

product: 421
company: 234
faq_item: 199
product embedding: 2067
faq embedding: 199
방금 원격 백엔드에서 직접 라벨 프린터 제품 보여줘 요청을 테스트했고, 제품 9개가 정상 반환됐습니다. 즉 백엔드/DB/임베딩 연결은 살아 있습니다.

스크린샷 화면은 제품/기업 검색 모드로 들어간 뒤 아직 질문을 입력하지 않은 상태라 메시지 영역이 비어 보이는 UI 흐름입니다. 질문을 입력하면 데이터가 나와야 합니다.

다만 네 말대로 “main 브랜치 배포 맞냐”는 질문에는 답이 아니오입니다. main 기준으로 다시 배포하려면 백엔드/프론트/qwen을 각각 main에서 다시 패키징해야 하는데, qwen main은 기본 모델이 Qwen3-Embedding-4B + Apple M4용 코드라 현재 LLM 서버에는 그대로 올리면 위험합니다.





오전 11:21
백엔드랑 프론트는 main브랜치 코드로 배포해야돼 qwen은 benchmark 브랜치 있는거로 배포하는거 맞아.
오전 11:22


이전 메시지 99개
알겠습니다. 정정해서 진행할게요: 백엔드/프론트는 main 브랜치 코드로 재배포, qwen은 현재처럼 benchmark 브랜치 배포 유지가 맞는 기준입니다. 로컬 브랜치를 checkout하지 않고 git archive main으로 main 코드만 패키징해서 서버에 올리겠습니다.


명령어 3개 실행
main 백엔드는 nginx가 80 -> api:8000으로 프록시하는 구조입니다. 그래서 프론트 main은 원격에서 http://52.64.112.27/api/v1을 보도록 빌드하고, 기존 DB 볼륨은 유지한 채 백엔드 컨테이너만 main 코드로 교체하겠습니다.


명령어 7개 실행
main 백엔드는 임베딩 테이블 이름도 현재 DB와 다릅니다. main 코드는 product_profile_embedding_1024 같은 suffix 테이블을 찾는데, 어제 복원한 DB는 product_profile_embedding 형태입니다. 그래서 백/프론트를 main으로 바꾸면 DB도 main 스키마 기준으로 다시 맞춰야 합니다. 우선 main 코드 배포와 동시에 DB 호환까지 처리하겠습니다.


명령어 3개 실행
main 코드 기준 배포 전에 DB 호환 작업도 같이 준비합니다. 기존 복원 DB에는 데이터가 있으니 날리지 않고, main이 찾는 *_embedding_1024 테이블을 기존 임베딩 테이블에서 복사 생성하는 방식으로 맞추겠습니다.

docker exec exmatch_rag_template_db psql -U postgres -d rag_template -t -A -F "|" -c "select table_name,column_name,data_type from information_schema.columns where table_name in ('company_profile_embedding','company_evidence_embedding','product_profile_embedding','product_evidence_embedding') order by table_name,ordinal_position;" 실행함
배포는 기존 원격 .env를 백업해 보존한 뒤 main 소스만 교체하는 방식으로 할게요. 백엔드는 main compose 구조를 따르되 API 직접 확인을 위해 8000:8000 포트 override도 유지하겠습니다.

$frontendDockerfile = @' FROM node:20-alpine WORKDIR /app COPY package*.json ./ RUN npm ci COPY . . ARG NEXT_PUBLIC_API_ENDPOINT ENV NEXT_PUBLIC_API_ENDPOINT=${NEXT_PUBLIC_API_ENDPOINT} RUN npm run build EXPOSE 3000 CMD ["npm", "run", "start", "--", "-p", "3000"] '@ $frontendCompose = @' services: frontend: build: context: . args: NEXT_PUBLIC_API_ENDPOINT: http://52.64.112.27/api/v1 container_name: exmatch_frontend ports: - "3000:3000" restart: unless-stopped '@ $frontendIgnore = @' .git node_modules .next *.log '@ $backendOverride = @' services: api: ports: - "8000:8000" '@ $deployScript = @' #!/usr/bin/env bash set -euo pipefail if [ -f "$HOME/exmatch-template/.env" ]; then cp "$HOME/exmatch-template/.env" "$HOME/exmatch-template.env.keep" fi rm -rf "$HOME/exmatch-template" "$HOME/exmatch-template-frontend" mkdir -p "$HOME/exmatch-template" "$HOME/exmatch-template-frontend" tar -xzf "$HOME/backend-main.tar.gz" -C "$HOME/exmatch-template" tar -xzf "$HOME/frontend-main.tar.gz" -C "$HOME/exmatch-template-frontend" if [ -f "$HOME/exmatch-template.env.keep" ]; then cp "$HOME/exmatch-template.env.keep" "$HOME/exmatch-template/.env" else cp "$HOME/exmatch-template/.env.example" "$HOME/exmatch-template/.env" fi cp "$HOME/backend.override.yml" "$HOME/exmatch-template/docker-compose.override.yml" cp "$HOME/frontend-main.Dockerfile" "$HOME/exmatch-template-frontend/Dockerfile" cp "$HOME/frontend-main.compose.yml" "$HOME/exmatch-template-frontend/docker-compose.yml" cp "$HOME/frontend-main.dockerignore" "$HOME/exmatch-template-frontend/.dockerignore" cd "$HOME/exmatch-template" set_kv() { local key="$1" local value="$2" if grep -q "^${key}=" .env; then sed -i "s|^${key}=.*|${key}=${value}|" .env else printf '%s=%s\n' "$key" "$value" >> .env fi } set_kv APP_ENV production set_kv APP_RELOAD 0 set_kv RUN_MIGRATIONS 1 set_kv DATABASE_URL postgresql+psycopg://postgres:postgres@db:5432/rag_template set_kv REDIS_URL redis://redis:6379/0 set_kv EMBED_PROVIDER qwen set_kv EMBED_API_URL http://10.0.30.118:4022 set_kv DEFAULT_EMBED_DIM 1024 set_kv CORS_ORIGINS http://52.64.112.27:3000,http://localhost:3000,http://127.0.0.1:3000 printf 'Prepared main branch web deployment.\n' '@ $compatSql = @' CREATE EXTENSION IF NOT EXISTS vector; DROP TABLE IF EXISTS company_profile_embedding_1024 CASCADE; DROP TABLE IF EXISTS company_evidence_embedding_1024 CASCADE; DROP TABLE IF EXISTS product_profile_embedding_1024 CASCADE; DROP TABLE IF EXISTS product_evidence_embedding_1024 CASCADE; CREATE TABLE company_profile_embedding_1024 AS SELECT company_id, content AS profile_text, content_hash::text AS content_hash, embedding, 'Qwen/Qwen3-Embedding-0.6B'::text AS embedding_model, 'legacy-import'::text AS template_version, created_at AS indexed_at, updated_at AS updated_at FROM company_profile_embedding; ALTER TABLE company_profile_embedding_1024 ADD PRIMARY KEY (company_id); CREATE TABLE company_evidence_embedding_1024 AS SELECT company_id, chunk_type::text AS field, 'ko'::text AS lang, content, content_hash::text AS content_hash, embedding, 'Qwen/Qwen3-Embedding-0.6B'::text AS embedding_model, 'legacy-import'::text AS template_version, created_at AS indexed_at, updated_at AS updated_at FROM company_evidence_embedding; ALTER TABLE company_evidence_embedding_1024 ADD PRIMARY KEY (company_id, field, lang); CREATE TABLE product_profile_embedding_1024 AS SELECT ppe.product_id, p.company_id, ppe.content AS profile_text, ppe.content_hash::text AS content_hash, ppe.embedding, 'Qwen/Qwen3-Embedding-0.6B'::text AS embedding_model, 'legacy-import'::text AS template_version, ppe.created_at AS indexed_at, ppe.updated_at AS updated_at FROM product_profile_embedding ppe JOIN product p ON p.id = ppe.product_id; ALTER TABLE product_profile_embedding_1024 ADD PRIMARY KEY (product_id); CREATE TABLE product_evidence_embedding_1024 AS SELECT pee.product_id, p.company_id, pee.chunk_type::text AS field, 'ko'::text AS lang, pee.content, pee.content_hash::text AS content_hash, pee.embedding, 'Qwen/Qwen3-Embedding-0.6B'::text AS embedding_model, 'legacy-import'::text AS template_version, pee.created_at AS indexed_at, pee.updated_at AS updated_at FROM product_evidence_embedding pee JOIN product p ON p.id = pee.product_id; ALTER TABLE product_evidence_embedding_1024 ADD PRIMARY KEY (product_id, field, lang); '@ [IO.File]::WriteAllText((Resolve-Path .deploy).Path + '\frontend-main.Dockerfile', $frontendDockerfile.Replace("`r`n","`n"), [Text.ASCIIEncoding]::new()) [IO.File]::WriteAllText((Resolve-Path .deploy).Path + '\frontend-main.compose.yml', $frontendCompose.Replace("`r`n","`n"), [Text.ASCIIEncoding]::new()) [IO.File]::WriteAllText((Resolve-Path .deploy).Path + '\frontend-main.dockerignore', $frontendIgnore.Replace("`r`n","`n"), [Text.ASCIIEncoding]::new()) [IO.File]::WriteAllText((Resolve-Path .deploy).Path + '\backend.override.yml', $backendOverride.Replace("`r`n","`n"), [Text.ASCIIEncoding]::new()) [IO.File]::WriteAllText((Resolve-Path .deploy).Path + '\deploy_main_web.sh', $deployScript.Replace("`r`n","`n"), [Text.ASCIIEncoding]::new()) [IO.File]::WriteAllText((Resolve-Path .deploy).Path + '\main_embedding_compat.sql', $compatSql.Replace("`r`n","`n"), [Text.ASCIIEncoding]::new()) Get-ChildItem .deploy\frontend-main.Dockerfile,.deploy\frontend-main.compose.yml,.deploy\backend.override.yml,.deploy\deploy_main_web.sh,.deploy\main_embedding_compat.sql | Select-Object Name,Length 실행함
컨텍스트가 자동으로 압축됨
확인했어요. 백엔드/프론트는 main 아카이브로 다시 올리고, qwen은 지금처럼 benchmark 배포를 유지하는 방향으로 진행할게요. 먼저 준비해둔 배포 파일을 웹서버로 넘긴 뒤 컨테이너를 다시 빌드하겠습니다.


명령어 4개 실행
로컬 준비물과 브랜치 기준 커밋은 맞습니다. 이제 웹서버에 main 배포 묶음을 전송하고 원격에서 압축 해제/환경값 정리까지 이어서 실행할게요.


명령어 2개 실행
전송과 원격 배치가 끝났습니다. git archive로 푼 배포본이라 원격 폴더에는 .git 정보가 없어서 rev-parse는 비어 보이지만, 묶음 자체는 방금 확인한 main 커밋에서 만든 파일입니다. 이제 백엔드 컨테이너를 main 코드로 빌드합니다.

ssh -i 'C:\Users\Momenti\Downloads\exmatch-publickey (1).pem' -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL exmatch2604@52.64.112.27 "cd ~/exmatch-template && docker compose up -d --build" 실행함
백엔드 이미지는 빌드됐는데 API 컨테이너가 healthcheck에서 떨어졌습니다. 여기서 멈추면 원인 없이 흔들리니, 바로 로그를 보고 main 코드가 기존 DB 스키마와 부딪힌 부분인지 확인하겠습니다.

ssh -i 'C:\Users\Momenti\Downloads\exmatch-publickey (1).pem' -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL exmatch2604@52.64.112.27 "cd ~/exmatch-template && docker compose ps && docker compose logs --tail=160 api" 실행함
원인은 코드 로직이 아니라 docker/entrypoint.sh의 CRLF 줄끝이었습니다. 원격 배포본의 실행 스크립트 줄끝을 LF로 정리한 뒤 이미지를 다시 빌드하겠습니다.


명령어 2개 실행
이번에는 Alembic 버전 충돌입니다. 기존 데이터베이스가 이전 배포 이력(0006)을 갖고 있는데 main 배포본의 마이그레이션 그래프와 맞지 않아 시작이 막혔어요. 이미 복원된 운영 데이터는 유지해야 하니, 자동 마이그레이션은 끄고 main 검색 코드가 찾는 1024 차원 임베딩 테이블만 호환 생성하겠습니다.

ssh -i 'C:\Users\Momenti\Downloads\exmatch-publickey (1).pem' -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL exmatch2604@52.64.112.27 "cd ~/exmatch-template && sed -i 's|^RUN_MIGRATIONS=.*|RUN_MIGRATIONS=0|' .env && docker compose cp ~/main_embedding_compat.sql db:/tmp/main_embedding_compat.sql && docker compose exec -T db psql -U postgres -d rag_template -f /tmp/main_embedding_compat.sql && docker compose up -d api nginx" 실행함
좋습니다, API가 healthy로 올라왔고 호환 임베딩 테이블도 데이터 수량대로 생성됐습니다. 이제 프론트도 main 코드로 다시 빌드해서 3000 포트에 붙이겠습니다.

ssh -i 'C:\Users\Momenti\Downloads\exmatch-publickey (1).pem' -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL exmatch2604@52.64.112.27 "cd ~/exmatch-template-frontend && docker compose up -d --build" 실행함
프론트 main 빌드도 성공했고 컨테이너가 재시작됐습니다. 마지막으로 실제 포트, DB 카운트, qwen 상태, 검색 스트림까지 확인해서 “데이터 없음” 문제가 배포 탓인지 여부를 끝까지 확인해볼게요.


명령어 6개 실행
검증 명령은 따옴표가 한 번 꼬였습니다. 결과 자체는 바뀐 게 아니고, 검증을 작은 명령들로 나눠서 다시 확인하겠습니다.


명령어 6개 실행
헬스체크와 테이블 건수는 정상입니다. 이제 검색 스트림은 따옴표 지옥을 피하려고 작은 스모크 스크립트로 확인하겠습니다. 로컬 .deploy에 검증용 파일 하나만 추가해서 서버에서 실행할게요.


파일 1개 생성,명령어 2개 실행함
스트림 테스트에서 첫 thread 생성이 500으로 실패했습니다. 이건 프론트 문제가 아니라 API가 기존 DB 스키마의 어떤 컬럼을 기대하는지 보는 단계라, 로그를 확인해서 필요한 호환 컬럼을 맞추겠습니다.


명령어 7개 실행
main은 채팅 테이블 이름은 같지만 컬럼명이 바뀐 버전입니다. 기존 thread_id/state/cards를 보존하면서 main이 쓰는 id/state_json/session_id/cards_json 컬럼을 추가해 맞추면 됩니다. 이벤트 테이블도 main에서 필수라 kprint 이벤트를 넣겠습니다.


파일 1개 생성,명령어 19개 실행함
이제 스키마는 넘어갔고, main 검색 SQL 자체에서 psycopg가 :event_slug IS NULL 파라미터 타입을 못 잡는 문제가 걸렸습니다. 실제 배포가 동작해야 하니 원격 main 코드에 최소 런타임 패치로 event_slug 파라미터를 text 캐스팅하고 API 이미지만 다시 빌드하겠습니다.


명령어 6개 실행
스모크 테스트 통과했습니다. 라벨 프린터 제품 보여줘에 실제 제품 5개가 반환됐어요. 마지막으로 외부에서 공개 IP로 프론트/API/qwen이 열리는지만 확인하고 정리해서 드릴게요.


명령어 4개 실행
배포 다시 맞췄습니다.

백엔드/프론트는 main 기준으로 재배포했고, qwen은 말씀하신 대로 benchmark 배포를 유지했습니다.

백엔드: main 7aad9e1
프론트: main c558fa9
qwen: benchmark 36f60ca
프론트 URL: 
http://52.64.112.27:3000
API health: 
http://52.64.112.27/api/v1/health
qwen health: 
http://15.135.211.14:4022/health
확인 결과 DB도 비어 있지 않습니다. company 234, product 421, faq_item 199, 제품 임베딩 421/2067건 들어 있고, 실제 스모크 테스트로 라벨 프린터 제품 보여줘를 호출했을 때 제품 5개가 정상 반환됐습니다.

중간에 main 코드와 기존 DB 스키마가 달라서 event, chat_session, product/company event_slug, *_embedding_1024 호환 테이블/컬럼을 추가했고, main 검색 SQL의 event_slug 타입 캐스팅 문제도 런타임 패치해서 컨테이너 재빌드했습니다. 이제 “데이터 없음”은 배포 데이터 누락 상태는 아닙니다. 브라우저에서 localhost:3000이 아니라 위 원격 프론트 주소로 열어서 확인해 주세요.

2개 파일 변경됨
+125
-0
실행 취소
리뷰

.deploy/smoke_main.py
.deploy/main_schema_compat.sql




오후 12:34
"C:\Users\Momenti\Downloads\안되는데.png"위에 사진처럼 뜨고, 참가업체 추천해줘라고 채팅 보냈는데 답변이 없는데?
오후 12:38


이전 메시지 60개
화면 캡처랑 실제 호출 흐름을 같이 볼게요. 먼저 이미지에서 어떤 에러/상태인지 확인하고, 이어서 로컬 localhost:3000이 어느 백엔드로 붙어 있는지도 점검하겠습니다.



이미지를 보니 데이터가 없는 화면이라기보다 “초기 인사 메시지”가 계속 누적되는 상태예요. 즉 프론트가 스레드를 반복 생성하거나, 저장된 세션/모드 전환 기록을 계속 다시 렌더링하는 쪽이 의심됩니다. 서버 로그에서 사용자가 보낸 참가업체 추천해줘 요청이 실제 API까지 들어왔는지 확인하겠습니다.


명령어 2개 실행
서버 로그상 사용자가 보낸 문장은 백엔드에 도달하지 않았고, 대신 같은 스레드에서 모드 변경 API만 계속 호출되고 있습니다. 프론트에서 버튼/모드 상태를 동기화하는 코드가 반복 호출을 만들고, 입력 전송까지 막는 흐름으로 보여요. 프론트 코드에서 mode 변경 훅과 채팅 전송 훅을 바로 확인해서 패치하겠습니다.


명령어 16개 실행
백엔드 로그를 보면 참가업체 추천해줘 스트림 요청 자체가 안 들어왔습니다. 대신 모드 버튼을 누를 때마다 “참관객 FAQ / 참가업체 FAQ / 제품·기업 검색” 전환 메시지가 누적되고 있어요. 전송 버튼/엔터 처리 쪽 또는 프론트 상태 저장 쪽 문제라서 프론트 코드를 고쳐서 배포까지 이어가겠습니다.

rg -n "onFinishHydration|persist|hasHydrated|useChatStore\.persist" src 실행함
수정 방향은 작게 잡겠습니다. 선택된 모드 버튼을 다시 눌러도 API를 호출하지 않게 막고, 프론트가 자체로 FAQ 인사 메시지를 추가로 붙이는 로직을 제거해서 서버가 내려준 메시지만 보여주게 하겠습니다. 그리고 Zustand hydration 체크는 현재 배포 환경에서 안전하게 optional API로 바꾸겠습니다.


명령어 4개 실행
중요한 원인 하나를 잡았습니다. 현재 모드 버튼을 같은 값으로 누를 때도 서버에 계속 “모드 변경”을 넣고 있었고, 프론트가 별도 인사 메시지를 또 붙여서 화면이 길게 쌓였습니다. 수정했으니 프론트 빌드를 먼저 통과시킨 뒤 배포하겠습니다.

npm run build 실행함
빌드는 통과했습니다. 이제 수정된 home.view.tsx 한 파일만 원격 프론트 소스에 반영하고 컨테이너를 다시 빌드하겠습니다.


명령어 2개 실행
원격 빌드가 실패했지만 기존 프론트 컨테이너는 그대로 살아 있습니다. 방금 로컬 작업 브랜치의 파일을 원격 main 위에 덮어써서 export 차이가 난 거라, main의 원본 파일을 기준으로 다시 패치해서 올리겠습니다. 이 부분은 제가 바로 복구할게요.


명령어 9개 실행
이번에는 main 원본 기준으로 다시 패치했고 로컬 빌드가 통과했습니다. 이제 이 파일을 원격에 다시 올려서 프론트 컨테이너를 재빌드하겠습니다.


명령어 2개 실행
배포는 성공했습니다. 다만 사용자의 브라우저에는 이미 잘못 누적된 chat-storage가 남아 있어서 새 코드가 떠도 예전 스레드를 다시 불러올 수 있습니다. 그래서 프론트 저장소 키를 새 버전으로 바꿔 기존 꼬인 로컬 상태를 자동으로 무시하게 한 번 더 패치하겠습니다.


명령어 5개 실행
로컬 작업 브랜치에는 main과 다른 디버그 로그 코드가 섞여 있어서 로컬 타입체크가 충돌했습니다. 원격은 main 기준 파일 세트라 그대로 원격 빌드를 진행하겠습니다.


파일 1개 생성,명령어 5개 실행함
맞아요, 화면 상태가 이상했습니다. 원인은 프론트 쪽이었어요.

수정해서 재배포했습니다.

같은 모드 버튼을 다시 눌러도 “참관객 FAQ / 참가업체 FAQ / 제품·기업 검색” 메시지가 계속 쌓이지 않게 막음
기존 브라우저에 저장된 꼬인 채팅 상태를 무시하도록 저장소 키를 chat-storage-v2로 변경
프론트 컨테이너 재빌드/재시작 완료
참가업체 추천해줘 백엔드 스모크 테스트 완료: 실제 참가업체 5개 응답 확인됨
지금 브라우저에서 한 번 새로고침, 가능하면 Ctrl + F5로 강력 새로고침 해주세요. 그다음 제품/기업 검색 선택하고 참가업체 추천해줘 보내면 답변이 나와야 합니다.

1개 파일 변경됨
실행 취소
리뷰

.deploy/smoke_company.py




오후 12:51
"C:\Users\Momenti\Downloads\참가업체 추천해줘.png" 여전히 참가업체 추천해줘 input 했을때 아무 결과값 안뜨는데?
오후 12:55



이전 메시지 20개
이번엔 “원격 배포는 정상인데 사용 중인 화면이 localhost:3000이라 다른 프론트를 보고 있는지”까지 같이 확인할게요. 캡처를 보고, 로컬 3000 프로세스와 원격 로그를 나란히 보겠습니다.



캡처상으로는 입력창에 문장이 그대로 남아 있어서, 백엔드 응답이 비어 있는 게 아니라 “전송 이벤트가 실행되지 않는” 상태에 가깝습니다. 원격 로그에서 방금 문장이 들어왔는지 확인하고, 프론트 버튼/엔터 핸들러 쪽을 더 직접적으로 막히지 않게 고치겠습니다.


명령어 4개 실행
로그를 보면 지금도 참가업체 추천해줘는 사용자의 브라우저에서 API로 전송되지 않았습니다. 대신 모드 전환만 계속 들어오고 있어요. 그래서 “전송 버튼 클릭/엔터”가 어떤 경우에도 직접 onSubmit을 타도록 입력 컴포넌트를 더 단단하게 고치고, 배포 후 캐시까지 덜 타게 처리하겠습니다.


파일 1개 수정,명령어 3개 실행함
확인해보니 백엔드에는 스모크 테스트는 정상 도달하지만, 사용자 화면에서는 전송 요청이 안 들어오고 있습니다. 입력 컴포넌트의 전송 버튼을 submit 의존이 아니라 명시적 onClick 전송으로 바꾸고, 기존 꼬인 브라우저 상태도 다시 한 번 새 저장소 키로 분리하겠습니다.


명령어 4개 실행
재빌드 완료됐습니다. 이제 공개 프론트가 떠 있는지 확인하고, 가능하면 실제 브라우저 쪽에서는 새 JS를 받도록 강제 새로고침이 필요합니다. 서버 헬스와 로그를 한 번 더 확인할게요.


명령어 2개 실행
맞습니다. 이번 캡처 기준으로는 “검색 결과가 안 뜨는” 문제가 아니라, 입력창의 참가업체 추천해줘가 전송 자체를 안 타고 있었습니다. 백엔드 로그에도 해당 문장이 안 들어왔고, 모드 전환 호출만 들어왔어요.

그래서 방금 추가로 수정/재배포했습니다.

전송 버튼을 form submit 의존이 아니라 명시적 onClick 전송으로 변경
한글 IME 입력 중 Enter 처리 꼬임 방지
기존 꼬인 브라우저 저장 상태를 또 무시하도록 chat-storage-v3로 변경
프론트 재빌드/재시작 완료
프론트 health 정상, 런타임 로그 오류 없음
지금은 반드시 Ctrl + F5로 강력 새로고침 한 번 해주세요. 기존 화면이 계속 남아 있으면 이전 JS/상태를 보고 있는 거라 새 코드가 안 먹습니다. 새로고침 후 제품/기업 검색 선택 → 참가업체 추천해줘 → 오른쪽 빨간 전송 버튼 클릭으로 다시 확인해 주세요.
`````

</details>
