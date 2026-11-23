# 남성 보세몰 AI 직원 — 7팀 오케스트레이션 보일러플레이트

남성 보세(사입) 쇼핑몰을 운영할 때 필요한 실무를 **7개 팀 + 총괄 오케스트레이터**로 나눈
파이썬 백엔드 뼈대입니다. 상품 1건을 넣으면

> MD 기획 → 디자인 → 콘텐츠 → 검수(QA) → **대표님 승인** → 개발(몰 등록) → 마케팅

순서로 자동 진행되고, **검수에서 걸리면 담당 팀으로 되돌아가 재작업**합니다.
실서버 배포·발주·광고비 집행처럼 되돌릴 수 없는 일은 반드시 대표님 승인 지점에서 멈춥니다.

---

## 0. 바로 열어보기 (설치 없이)

**라이브 데모: <https://252729rggz-hash.github.io/Hyum/>** (저장소: <https://github.com/252729rggz-hash/Hyum>)

`docs/index.html` 한 파일에 UI와 데모 엔진이 들어 있어, 서버 없이 브라우저에서 바로 동작합니다.
아이폰 사파리에서 열면 회의실 캐릭터·결재 카드·승인/반려 흐름을 그대로 눌러볼 수 있습니다.

- 처음 열면 샘플 상품(에어 턴 오버핏 바람막이 · 사입 21,000원 → 판매 92,900원 · 순이익률 55.1% · 검수 100점)이
  **결재 대기 1건**으로 올라와 있고, 회의실 말풍선에 "대표님, 오늘 결재하실 건 이거 하나예요."가 떠 있습니다.
- `📊 대시보드 → 🚀 샘플 상품으로 런칭`을 누르면 MD → 디자인 → 콘텐츠 → 검수 단계가 회의실 캐릭터·활동 로그에
  실시간으로 흐르고, `📋 대표 할 일`에서 `[승인]`/`[반려]`를 누르면 개발 등록 → 마케팅 세팅 → 완료까지 이어집니다.
- 데모는 **브라우저 안에서만** 동작합니다. 실제 LLM 호출·몰 상품 등록·광고 집행은 하지 않고, 새로고침하면 처음 상태로 돌아갑니다.

로컬에서 FastAPI로 돌릴 때는 기존 `app/web/index.html`이 그대로 쓰이고(4초 자동 갱신·실제 API),
GitHub Pages 같은 정적 호스팅에서는 `docs/index.html`이 데모 엔진으로 자동 전환됩니다.

`app/web/index.html`을 고친 뒤 데모도 갱신하려면:

```bash
python3 scripts/build_docs.py   # docs/index.html 재생성 (데모 엔진: scripts/demo_engine.js)
```

---

## 1. 팀 구성

| 팀 | 패키지 | 하는 일 | 주요 산출물 |
|---|---|---|---|
| 총괄 | `app/orchestrator` | 팀 배치, 상태 관리, 승인 지점, 재작업 라우팅 | `MallWorkflowState`, LangGraph |
| MD·상품기획 | `app/teams/md` | 트렌드/키워드, 마진·판매가 역산, 소싱 리스트 | `MDPlan`, `PricingPlan` |
| 디자인 | `app/teams/design` | 상세페이지 레이아웃, 썸네일·배너·룩북 규격 | `DesignPlan`, `DesignAsset` |
| 콘텐츠 | `app/teams/content` | SEO 제목, 핏·소재·코디 카피, 릴스 원고 | `ContentCopy` |
| 검수(QA) | `app/teams/qa` | 가격 오기·오탈자·과장광고·규격·누락 검사 | `QAReport`, `QACheck` |
| 개발 | `app/teams/dev` | 몰 상품 등록, 재고 동기화 | `DevDeployment` |
| 마케팅 | `app/teams/marketing` | 메타/네이버 소재·예산·ROAS 설계 | `MarketingPlan` |
| CS·운영 | `app/teams/cs` | 사이즈·배송·교환·반품 응대 초안 | `CSPlaybook` |

CS팀은 배포 후 주문이 들어온 뒤 상시 도는 팀이라 메인 워크플로에는 넣지 않고,
같은 상품 상태로 단독 실행할 수 있게 분리했습니다.

### 팀별 프롬프트·도구 (32개)

각 팀 `agent.py`는 **한국어 시스템 프롬프트**(역할·규칙·금지사항·출력 스키마)와
**사용자 메시지 템플릿**(`build_prompt()`), 그리고 **타입이 잡힌 도구**(`tools.py`)를 가집니다.
`GET /teams/catalog`에서 전체 프롬프트 요약과 도구 JSON Schema를 볼 수 있습니다.

| 팀 | 시스템 프롬프트가 고정하는 것 | 도구 |
|---|---|---|
| MD | 판매가 역산(공급가·몰 수수료·PG 수수료·배송 원가·부가세·반품충당금), 최소 마진 25%, 사이즈 커브·MOQ, 리오더 규칙 | `md_price_quote` `md_size_curve` `md_allocate_initial_order` `md_reorder_signal` `md_sourcing_plan` |
| 디자인 | 모바일 우선 섹션 8단(후킹→룩북→핏→디테일→소재→사이즈표→코디→고시), 규격 860/1000×1000/1920×600/1200×1600 | `ds_detail_blueprint` `ds_asset_spec` `ds_image_prompt` `ds_palette` |
| 콘텐츠 | 네이버 50자 제목, 금지 표현, 체형별 핏, 혼용률 기반 세탁, 숏폼 4비트, 고시정보 6항목 | `cn_seo_title` `cn_fit_guide` `cn_care_guide` `cn_disclosure` `cn_shortform_script` `cn_hashtags` |
| QA | 표시광고법·의료법 금지어, 역마진, 부가세 정합성, 고시 누락, 에셋 규격, 반려 기준(critical/major) | `qa_scan_claims` `qa_margin_guard` `qa_disclosure_guard` `qa_asset_guard` |
| 개발 | 승인 범위 밖 가격 변경 금지, 옵션 코드 규칙, 재고 0 옵션 숨김, 플랫폼별 payload, 임계 알림 | `dev_option_matrix` `dev_product_payload` `dev_stock_alert` |
| 마케팅 | 손익분기 ROAS = 1÷마진율, 최대 CPA = 객단가×마진율, 채널별 소재 규칙, 광고비 승인 | `mk_budget_split` `mk_roas_break_even` `mk_ad_hooks` `mk_targeting` |
| CS | 존댓말 3단 구조(공감→사실→다음 행동), 교환 7일·반품비 6,000원, 자동 발송 금지 기준 | `cs_size_chart` `cs_exchange_guide` `cs_return_quote` `cs_shipping_delay_notice` `cs_defect_intake` `cs_escalation_decision` |

도구는 세 가지 방식으로 쓰입니다.

```python
from app.teams.md import agent as md
from app.shared.tooling import openai_tools, anthropic_tools, dispatch

md.build_prompt(product)              # 1) 사용자 메시지 문자열
md.build_messages(product)            # 2) [system, user] messages
openai_tools("md")                    # 3) function calling 스키마
anthropic_tools("md")                 #    (Anthropic input_schema)
dispatch("md", "md_price_quote", {...})  # LLM이 고른 도구 실행 (팀 범위 밖 차단)
```

## 2. 흐름

```
START
  │
  ▼
[MD] ──► [디자인] ──► [콘텐츠] ──► [검수 QA]
                                      │
              ┌───────────────────────┼────────────────────────┐
              │ 통과                   │ 반려 (가격/재고→MD,     │ 재작업 한도 초과
              ▼                       │  규격→디자인, 카피→콘텐츠)│
      [대표님 승인] ◄──────────────────┘                        ▼
        │      │                                        [차단·보고] → END
   승인 │      │ 반려
        ▼      ▼
      [개발]  END
        │
        ▼
   [마케팅] → END
```

- 승인은 LangGraph `interrupt()`로 구현되어 워크플로가 **실제로 멈추고 상태가 저장**됩니다.
  `POST /workflows/{id}/approval`로 재개합니다.
- 재작업 횟수는 `QA_MAX_REVISIONS`(기본 2회)로 제한합니다. 넘으면 `qa_blocked`로 끝나고
  대표님 확인 대상이 됩니다.
- 광고비 증액, 발주·결제, 대량 고객 발송도 같은 승인 패턴(`ApprovalKind`)으로 확장할 수 있습니다.

## 3. 기술 스택

| 영역 | 선택 | 이유 |
|---|---|---|
| API | FastAPI + Uvicorn | 웹훅/크론/대시보드 모두 붙이기 쉬운 비동기 API |
| 오케스트레이션 | LangGraph 1.x | 조건부 분기·재시도·휴먼인더루프를 그래프로 명시 |
| 스키마 | Pydantic v2 + pydantic-settings | 팀 간 계약을 타입으로 고정, 설정 검증 |
| HTTP | httpx | 카페24/아임웹/자체몰 API 호출 |
| 저장(예정) | PostgreSQL + Redis | 상품/승인 이력은 PG, 진행 상태·큐는 Redis |
| LLM | OpenAI/Anthropic (교체 가능) | 지금은 `LLM_PROVIDER=mock`으로 키 없이 동작 |

## 4. 프로젝트 구조

```
mens-mall-agents/
├── README.md
├── pyproject.toml
├── .env.example
├── tests/
│   ├── test_pipeline.py            # 프롬프트·도구·마진·검수·워크플로 스모크 테스트
│   └── test_dashboard.py           # 라이브 오피스 UI·/workflows·/office/state 테스트
└── app/
    ├── main.py                     # FastAPI (/health, /teams/catalog, /workflows/*, /office/state)
    ├── web/index.html              # 라이브 오피스 UI (임베드 CSS/JS, 외부 빌드 없음)
    ├── shared/
    │   ├── config.py               # Settings (pydantic-settings)
    │   ├── models.py               # ProductItem, PricingPlan, ProductDisclosure 등 공용 스키마
    │   ├── prompting.py            # 팀별 PromptBundle 레지스트리
    │   └── tooling.py              # Tool 레지스트리 + OpenAI/Anthropic 스키마 + dispatch
    ├── orchestrator/
    │   ├── state.py                # MallWorkflowState
    │   └── graph.py                # StateGraph 조립 + 승인/재작업 라우팅
    ├── teams/
    │   ├── md/        agent.py + tools.py   # 마진·사이즈 커브·초도 배분·리오더·사입처
    │   ├── design/    agent.py + tools.py   # 상세페이지 설계·규격·이미지 프롬프트·팔레트
    │   ├── content/   agent.py + tools.py   # SEO·핏 가이드·세탁·고시정보·숏폼·해시태그
    │   ├── qa/        agent.py + tools.py   # 금지 표현·마진 가드·고시 가드·에셋 가드
    │   ├── dev/       agent.py + tools.py   # 옵션 조합·payload·재고 알림
    │   ├── marketing/ agent.py + tools.py   # 예산·ROAS 손익분기·광고 훅·타겟팅
    │   └── cs/        agent.py + tools.py   # 사이즈표·교환·반품·지연·불량·에스컬레이션
    └── integrations/
        ├── mall_adapter.py         # MallAdapter ABC + Cafe24/Imweb/Custom 스텁
        └── notifications.py        # 승인 요청 알림 스텁(웹훅/로그)
```

## 5. 실행 방법

```bash
cd mens-mall-agents
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .

cp .env.example .env          # 값은 그대로 둬도 됩니다 (mock 모드)
uvicorn app.main:app --reload --port 8000
```

- `LLM_PROVIDER=mock`, `MALL_API_KEY`가 비어 있으면 **외부 호출 없이 전체 흐름이 끝까지 돕니다.**
  이때 개발팀은 `simulated=true`로 표시된 시뮬레이션 등록을 남깁니다(실서버 미반영).
- `APP_ENV=prod`에서는 자격증명이 없으면 배포를 실패 처리합니다.

### 라이브 오피스 웹 UI

서버를 켜고 <http://localhost:8000> 을 열면 바로 뜨는 화면입니다(`app/web/index.html`).
레트로 OS 창 스타일 3탭:

| 탭 | 내용 |
|---|---|
| 🎮 라이브 오피스 | 오늘 결재 요약 + 파이프라인, `대표 승인 회의실` 픽셀 캐릭터 8명(대표+팀장 7)과 말풍선, 활동 로그, `staff.roster`(팀별 상태·월급 0원) |
| 📊 대시보드 | KPI 4종, 샘플 상품 1클릭 런칭(또는 직접 입력), 실행 목록, 7개 팀 · 32개 도구 카탈로그 |
| 📋 대표 할 일 | 결재 대기 안: 사입가/판매가/순이익/마진·QA 점수·디자인·콘텐츠 요약 → `[승인]`/`[반려]` |

화면은 4초마다 `GET /office/state`·`GET /workflows`를 다시 읽어 실시간으로 갱신합니다.
승인·반려는 `POST /workflows/{id}/approval`을 그대로 호출합니다.

| 엔드포인트 | 용도 |
|---|---|
| `GET /` | 라이브 오피스 웹 UI |
| `GET /office/state` | 팀장 7명 로스터·회의실 말풍선·최근 활동 로그·파이프라인 |
| `GET /workflows` | 실행 전체 목록(상태·단계·가격·마진·QA 점수·승인 요청) |

> 실행 목록·활동 로그는 서버 프로세스의 인메모리 저장소에 있습니다. `--reload`로 코드를 고치면
> 함께 초기화되고, 승인 대기 중이던 워크플로도 사라집니다(체크포인터와 같은 수명).
> 재시작 후에도 남기려면 `InMemorySaver`를 `SqliteSaver`/`PostgresSaver`로 바꾸고 목록도 DB에 옮기면 됩니다.

### 상품 1건 실행

```bash
curl -s -X POST http://localhost:8000/workflows/launch \
  -H 'Content-Type: application/json' \
  -d '{
    "product": {
      "sku": "MN-OUT-2611-001",
      "name": "에어 턴 오버핏 바람막이",
      "category": "남성 아우터 > 바람막이",
      "fit": "oversized",
      "material": "폴리에스터 100%",
      "color_options": ["블랙", "차콜", "아이보리"],
      "size_options": ["M", "L", "XL", "2XL"],
      "cost_price": 21000,
      "stock": 45,
      "supplier": "동대문 A도매",
      "keywords": ["남자 바람막이", "오버핏 아우터"]
    }
  }' | python -m json.tool
```

응답은 `status: "awaiting_approval"`과 함께 `approval`(판매가·마진·리스크), `qa_report`를 돌려줍니다.

### 승인 / 반려

```bash
# 승인 → 개발 → 마케팅까지 진행
curl -s -X POST http://localhost:8000/workflows/wf_xxxx/approval \
  -H 'Content-Type: application/json' \
  -d '{"approved": true, "decided_by": "대표", "note": "등록 진행"}'

# 반려 → 워크플로 종료 (상태 rejected)
curl -s -X POST http://localhost:8000/workflows/wf_xxxx/approval \
  -H 'Content-Type: application/json' \
  -d '{"approved": false, "note": "가격 재검토"}'
```

### 상태 조회

```bash
curl -s http://localhost:8000/workflows/wf_xxxx | python -m json.tool
```

## 6. 실제 연동으로 바꾸는 지점

| 지금(스텁) | 바꿀 곳 |
|---|---|
| 규칙 기반 카피/기획 | 각 `agent.py`의 `SYSTEM_PROMPT` + `USER_TEMPLATE` + `build_messages()`를 LLM 호출로 교체하고, `openai_tools(team)`을 바인딩한 뒤 `dispatch(team, name, args)`로 도구를 실행 |
| 로그/웹훅 알림 | `integrations/notifications.py` → 슬랙·카카오 알림톡 |
| 카페24/아임웹/자체몰 | `integrations/mall_adapter.py`의 어댑터 (OAuth 토큰·재시도 정책 추가) |
| 인메모리 체크포인트 | `orchestrator/graph.py`의 `InMemorySaver` → `SqliteSaver`/`PostgresSaver` |
| 이미지 생성 | `ds_image_prompt`가 만든 프롬프트 → 이미지 생성 API, 결과를 `DesignAsset.file_url`에 채우기 |

## 7. 검증

```bash
python3 -m compileall app            # 문법 검사
ruff check .                         # 린트
pytest -q tests                      # 프롬프트·도구·마진·검수·워크플로·UI
uvicorn app.main:app &               # 실제 기동
curl localhost:8000/health
curl localhost:8000/teams/catalog   # 팀별 프롬프트·도구 스키마
curl localhost:8000/office/state    # 라이브 오피스 상태
```

확인된 동작(로컬 mock 기준)

- `/health` 200, `/teams/catalog` 200 (팀 7개 · 도구 32개)
- 정상 상품: `awaiting_approval` → 승인 → `completed` (개발 시뮬레이션 등록 + 마케팅 플랜)
- 승인 반려: `rejected`로 종료
- 판매가를 원가 미만으로 넣은 상품: QA 반려 → MD 재작업 2회 → `qa_blocked`

> 가격 계산이 바뀌었습니다: 예전에는 몰 수수료·배송 원가만 반영했지만, 이제 **PG 수수료(1.8%)와
> 반품·불량 충당금(5%)**까지 차감합니다. README 예시 상품(공급가 21,000원)의 권장 판매가는
> 73,900원 → 92,900원이 되고, 순이익률은 55.1%입니다. 두 항목은 `.env`의
> `PAYMENT_FEE_RATE`·`RETURN_RESERVE_RATE`로 조정합니다.

## 8. 다음 단계 제안

1. **DB 연결**: 상품·승인·배포 이력을 PostgreSQL에 남기고, 체크포인터를 `PostgresSaver`로.
2. **LLM 연결**: `LLM_PROVIDER=openai` + 팀별 프롬프트 튜닝. QA만은 규칙+LLM 2단 검수 권장.
3. **CS 자동화**: 주문 웹훅 → 문의 분류 → 템플릿 초안 → 3만원 이상은 승인 큐.
4. **대시보드**: 승인 대기 목록, SKU별 마진/ROAS, 재고 소진율 한 화면. (1차 버전은 `GET /` 라이브 오피스)
5. **권한 분리**: 승인 API에 대표 계정 인증(토큰/2FA) 추가.
