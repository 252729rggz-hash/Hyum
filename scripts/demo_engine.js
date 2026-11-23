  /* ══════════════════════════════════════════════════════════════════
     데모 엔진 — FastAPI가 없는 정적 호스팅(GitHub Pages)용
     --------------------------------------------------------------
     서버가 없을 때 `api()`가 이 엔진으로 위임됩니다. app/main.py의
     상태 계산(팀 상태·말풍선·파이프라인·활동 로그)과 app/teams/md/tools.py의
     가격 계산 규칙을 브라우저에서 그대로 재현합니다. 실제 LLM 호출,
     몰 API 등록, 광고 집행은 하지 않습니다(전부 시뮬레이션).
     ══════════════════════════════════════════════════════════════════ */
  const LOCAL_HOST = /^(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:\d+)?$/;
  const DEMO_MODE =
    location.protocol === "file:" ||
    /(^|\.)github\.io$/.test(location.hostname) ||
    !LOCAL_HOST.test(location.host) ||
    /[?&]demo=1/.test(location.search);

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  // 회의실 픽셀 캐릭터 — app/main.py의 STAFF/CEO와 동일 (월급만 데모용 예시값)
  const STAFF = [
    { team: "md", team_label: "상품기획", name: "송민재", role: "MD", badge: "MD", avatar: "🧮", slot: 4, color: "#f4a7b9", hair: "#3b2f2a", shirt: "#f4a7b9", pants: "#5a4a5e", salary_monthly: 3400000 },
    { team: "design", team_label: "디자인", name: "최아름", role: "디자인", badge: "디자인", avatar: "🎨", slot: 1, color: "#9ecbe8", hair: "#4a3b32", shirt: "#9ecbe8", pants: "#45516b", salary_monthly: 3100000 },
    { team: "content", team_label: "콘텐츠", name: "김세리", role: "콘텐츠", badge: "콘텐츠", avatar: "✍️", slot: 2, color: "#f6d48f", hair: "#2f2a28", shirt: "#f6d48f", pants: "#5e4a3a", salary_monthly: 3000000 },
    { team: "qa", team_label: "검수", name: "한도빈", role: "검수", badge: "QA", avatar: "🔍", slot: 3, color: "#b7e4c7", hair: "#3b2f2a", shirt: "#b7e4c7", pants: "#3f5148", salary_monthly: 3200000 },
    { team: "dev", team_label: "개발", name: "이지혜", role: "개발", badge: "DEV", avatar: "💻", slot: 5, color: "#c3b4ee", hair: "#2b2b33", shirt: "#c3b4ee", pants: "#3d3a52", salary_monthly: 3800000 },
    { team: "marketing", team_label: "마케팅", name: "박지훈", role: "마케팅", badge: "MKT", avatar: "📣", slot: 6, color: "#f8b26a", hair: "#4a362e", shirt: "#f8b26a", pants: "#4c3a30", salary_monthly: 3300000 },
    { team: "cs", team_label: "고객응대", name: "윤하늘", role: "CS", badge: "CS", avatar: "🎧", slot: 7, color: "#e9e3cf", hair: "#3b2f2a", shirt: "#efe8d4", pants: "#4a4a55", salary_monthly: 2900000 }
  ];
  const CEO_ROW = { team: "ceo", team_label: "대표", name: "현민", role: "대표", avatar: "👑", color: "#3e4a6b", hair: "#26202a", shirt: "#3e4a6b", pants: "#2c3247" };

  const STAGE_LABELS = {
    md: "상품기획", design: "디자인", content: "콘텐츠", qa: "검수", approval: "대표 승인",
    dev: "개발·등록", marketing: "마케팅", done: "완료", blocked: "확인 필요", rejected: "반려"
  };
  const STAGE_PROGRESS = { md: 10, design: 25, content: 40, qa: 55, approval: 70, dev: 85, marketing: 95, done: 100, blocked: 55, rejected: 60 };
  const STAGE_TEAM_INDEX = { md: 0, design: 1, content: 2, qa: 3, approval: 3, blocked: 3, rejected: 3, dev: 4, marketing: 5, done: 6 };
  const PIPE_STAGES = ["md", "design", "content", "qa", "approval", "dev", "marketing"];
  const TEAM_SEQ = ["md", "design", "content", "qa", "dev", "marketing", "cs"];

  const TASK = {
    md: { working: "'{n}' 마진·초도 발주 계산", done: "'{n}' 판매가·발주 확정", idle: "신상품 사입가·마진 계산 대기" },
    design: { working: "'{n}' 상세페이지 레이아웃 설계", done: "'{n}' 상세 컷·배너 시안 완료", idle: "상세페이지 템플릿 정리 중" },
    content: { working: "'{n}' SEO 카피·고시정보 작성", done: "'{n}' 카피·릴스 대본 완료", idle: "카피 라이브러리 정리 중" },
    qa: { working: "'{n}' 표시광고법·가격 검수", done: "'{n}' 검수 통과", idle: "검수 체크리스트 점검 중" },
    dev: { working: "'{n}' payload 생성·재고 동기화", done: "'{n}' 몰 등록 완료", idle: "상품 등록 양식 대기 중" },
    marketing: { working: "'{n}' 메타·네이버 캠페인 설계", done: "'{n}' 캠페인 세팅 완료", idle: "지난 캠페인 ROAS 복기 중" },
    cs: { working: "'{n}' 교환·반품 응대 중", done: "'{n}' 응대 종료", idle: "응대 템플릿 다듬는 중" }
  };
  function taskText(team, kind, name) {
    const tpl = (TASK[team] || {})[kind];
    return tpl ? tpl.replace("{n}", name) : "";
  }

  // 몰 조건 — app/shared/config.py 기본값과 동일
  const RULES = { vat: 0.1, platform: 0.035, payment: 0.018, reserve: 0.05, shipping: 3000, targetMargin: 0.55, minMargin: 0.25 };
  const PENALTIES = { critical: 30, major: 8, minor: 2 };

  const demo = { startedAt: new Date().toISOString(), workflows: [], activity: [] };

  function demoLog(message, team, kind, at) {
    demo.activity.push({ at: at || new Date().toISOString(), team: team || "orchestrator", message: message, kind: kind || "info" });
    if (demo.activity.length > 120) demo.activity.splice(0, demo.activity.length - 120);
  }

  function fmt(n) { return Number(n || 0).toLocaleString("ko-KR"); }

  /* ── 판매가·마진 (app/teams/md/tools.py price_quote 재현) ── */
  function roundPsych(value) {
    if (value <= 0) return 0;
    const step = value >= 100000 ? 10000 : 1000;
    return Math.max(Math.ceil(value / step) * step - 100, 100);
  }

  function priceQuote(cost, given) {
    const netRatio = 1 / (1 + RULES.vat) * (1 - RULES.platform) - RULES.payment - RULES.reserve;
    const warnings = [];
    let selling, basis;
    if (given) {
      selling = given;
      basis = "입력 판매가 기준 검증";
    } else if (netRatio - RULES.targetMargin > 0.05) {
      selling = roundPsych((cost + RULES.shipping) / (netRatio - RULES.targetMargin));
      basis = "목표 순이익률 55% 역산";
    } else {
      selling = roundPsych(cost * 2.2);
      basis = "목표 마진 구조 불가 → 공급가 2.2배 보수 책정";
      warnings.push("수수료·충당금 합계가 목표 마진을 잠식합니다 — 마진 목표 하향 또는 공급가 재협상 필요");
    }
    const vat = Math.round(selling * RULES.vat / (1 + RULES.vat));
    const netRevenue = selling - vat;
    const platformFee = Math.round(netRevenue * RULES.platform);
    const paymentFee = Math.round(selling * RULES.payment);
    const returnReserve = Math.round(selling * RULES.reserve);
    const netProfit = netRevenue - platformFee - paymentFee - returnReserve - cost - RULES.shipping;
    const margin = selling ? Math.round(netProfit / selling * 10000) / 10000 : 0;
    const markup = cost ? Math.round(selling / cost * 100) / 100 : 0;
    if (netProfit <= 0) warnings.push("역마진: 판매가에서 원가·수수료·충당금을 빼면 손실입니다");
    else if (margin < RULES.minMargin) warnings.push("순이익률 " + (margin * 100).toFixed(1) + "% — 최소 기준 25% 미달");
    if (cost && markup < 2.0) warnings.push("판매 배수 " + markup.toFixed(1) + "배 — 보세몰 통상 2.2배 이상 필요");
    if (cost && markup >= 4.0) warnings.push("판매 배수 " + markup.toFixed(1) + "배 — 통상 2.2~3.0배보다 높음. 경쟁 상품 시장가 확인 필요");
    return {
      selling: selling, cost: cost, vat: vat, platformFee: platformFee, paymentFee: paymentFee,
      returnReserve: returnReserve, shipping: RULES.shipping, netProfit: netProfit,
      margin: margin, markup: markup, basis: basis, warnings: warnings
    };
  }

  /* ── 검수 (app/teams/qa/agent.py 규칙 축약) ── */
  function qaReport(quote) {
    const checks = [];
    if (quote.selling <= 0) checks.push({ code: "PRICE_POSITIVE", severity: "critical", passed: false, message: "판매가가 0원 이하입니다" });
    if (quote.selling < quote.cost) checks.push({ code: "PRICE_NOT_BELOW_COST", severity: "critical", passed: false, message: "판매가(" + fmt(quote.selling) + "원)가 공급가(" + fmt(quote.cost) + "원)보다 낮습니다 (역마진)" });
    if (quote.netProfit <= 0) checks.push({ code: "PRICE_LOSS", severity: "critical", passed: false, message: "수수료·배송·충당금 반영 후 순이익이 " + fmt(quote.netProfit) + "원입니다" });
    if (quote.margin < RULES.minMargin) checks.push({ code: "PRICE_MARGIN", severity: "major", passed: false, message: "순이익률 " + (quote.margin * 100).toFixed(1) + "% — 최소 기준 25% 미달, 가격 재산정 필요" });
    checks.push({ code: "CLAIM_SCAN", severity: "critical", passed: true, message: "금지·과장 표현 0건 (표시광고법)" });
    checks.push({ code: "DISCLOSURE_GUARD", severity: "critical", passed: true, message: "고시 필수 항목(혼용률·제조국·세탁법) 충족" });
    checks.push({ code: "ASSET_GUARD", severity: "major", passed: true, message: "상세페이지·썸네일·배너 규격 정상" });
    const failed = checks.filter((c) => !c.passed);
    const score = Math.max(0, 100 - failed.reduce((sum, c) => sum + (PENALTIES[c.severity] || 2), 0));
    const blocking = failed.some((c) => c.severity === "critical" || c.severity === "major");
    return {
      passed: !blocking,
      score: score,
      checks: checks,
      feedback: failed.map((c) => "[md] " + c.code + ": " + c.message)
    };
  }

  function demoDesign(product) {
    const fitLabel = { oversized: "오버핏", slim: "슬림핏", loose: "루즈핏", regular: "레귤러핏" }[product.fit] || "레귤러핏";
    return {
      concept: "muted 뉴트럴 · " + fitLabel + " 실루엣 강조 · 클린 스튜디오 배경",
      mood_keywords: ["clean", "minimal", "editorial", "muted", product.fit || "regular"],
      assets: [
        { kind: "detail_page", name: product.sku + "_detail", size: "860x4200" },
        { kind: "thumbnail", name: product.sku + "_thumb", size: "1000x1000" },
        { kind: "banner", name: product.sku + "_banner", size: "1920x600" },
        { kind: "lookbook", name: product.sku + "_lookbook", size: "1200x1600" }
      ]
    };
  }

  function demoContent(product) {
    const leaf = String(product.category || "남성 의류").split(">").pop().trim();
    const fitLabel = { oversized: "오버핏", slim: "슬림핏", loose: "루즈핏", regular: "레귤러핏" }[product.fit] || "레귤러핏";
    return {
      seo_title: (product.name + " " + fitLabel + " 남자 " + leaf + " 데일리").slice(0, 50),
      hook: "어깨선 하나로 달라지는 실루엣, " + product.name + ".",
      hashtags: ["#남성패션", "#오버핏", "#남자바람막이", "#데일리룩", "#출근룩", "#남친룩", "#가을코디", "#무료배송", "#신상", "#남성의류"],
      disclosure_missing: []
    };
  }

  function demoApproval(rec) {
    const risks = ["실서버에 상품이 공개되면 즉시 고객 주문이 들어올 수 있습니다."];
    risks.push("MALL_API_KEY 미설정 — 이 환경에서는 시뮬레이션 등록으로 처리됩니다.");
    (rec._quote.warnings || []).slice(0, 2).forEach((w) => risks.push(w));
    if (rec._product && rec._product.supplier) {
      risks.push("사입처(" + rec._product.supplier + ") 실재고·단가 확인 전 '확정 발주'로 단정하지 않습니다.");
    }
    return {
      id: "apr_" + rec.workflow_id.slice(3),
      workflow_id: rec.workflow_id,
      kind: "deploy",
      title: "'" + rec.name + "' 상품 등록 승인 요청",
      summary: "SKU " + rec.sku + " / 판매가 " + fmt(rec.selling_price) + "원 / 순이익률 " + (rec.margin_rate * 100).toFixed(1) +
        "% / 검수 " + rec.qa_score + "점. custom 몰에 상품을 등록하고 재고를 동기화합니다.",
      requested_by: "orchestrator",
      payload: {
        sku: rec.sku, name: rec.name, selling_price: rec.selling_price, cost_price: rec.cost_price,
        margin_rate: rec.margin_rate, stock: rec.inventory.stock, platform: "custom", qa_score: rec.qa_score
      },
      risks: risks.slice(0, 4),
      status: "pending",
      created_at: rec.created_at
    };
  }

  function buildRecord(product, createdAt) {
    const quote = priceQuote(product.cost_price, product.selling_price);
    const qa = qaReport(quote);
    const rec = {
      workflow_id: "wf_" + Math.random().toString(16).slice(2, 14),
      sku: product.sku || "MN-DEMO-000",
      name: product.name || "신상품",
      category: product.category || "남성 의류",
      status: "awaiting_approval",
      stage: "approval",
      stage_label: STAGE_LABELS.approval,
      progress: STAGE_PROGRESS.approval,
      created_at: createdAt || new Date().toISOString(),
      updated_at: new Date().toISOString(),
      cost_price: product.cost_price,
      selling_price: quote.selling,
      margin_rate: quote.margin,
      net_profit: quote.netProfit,
      break_even_units: quote.netProfit > 0 ? 1 : 0,
      qa_score: qa.score,
      qa_passed: qa.passed,
      qa_feedback: qa.feedback,
      design: demoDesign(product),
      content: demoContent(product),
      inventory: { stock: product.stock || 0, supplier: product.supplier || "직접 입력" },
      deployed: null,
      note: product.note || "대시보드 1클릭 런칭",
      _quote: quote,
      _qa: qa,
      _product: product
    };
    rec.approval = demoApproval(rec);
    return rec;
  }

  function brief(rec) {
    const ap = rec.approval || {};
    return {
      workflow_id: rec.workflow_id, sku: rec.sku, name: rec.name, status: rec.status,
      stage_label: rec.stage_label, selling_price: rec.selling_price, margin_rate: rec.margin_rate,
      qa_score: rec.qa_score, title: ap.title || ("'" + rec.name + "' 승인 요청"),
      risks: (ap.risks || []).slice(), created_at: rec.created_at
    };
  }

  function sortedRuns() {
    return demo.workflows.slice().sort((a, b) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0));
  }

  function teamStatus(active) {
    const statuses = {}, tasks = {};
    TEAM_SEQ.forEach((team) => { statuses[team] = "대기 중"; tasks[team] = taskText(team, "idle", ""); });
    if (!active) return { statuses: statuses, tasks: tasks };
    const stage = active.stage || "md";
    const name = active.name || "신상품";
    if (stage === "approval") {
      TEAM_SEQ.slice(0, 3).forEach((team) => { statuses[team] = "완료"; tasks[team] = taskText(team, "done", name); });
      statuses.qa = "결재 대기";
      tasks.qa = "'" + name + "' 등록 승인 대기";
      return { statuses: statuses, tasks: tasks };
    }
    if (stage === "blocked") {
      TEAM_SEQ.slice(0, 3).forEach((team) => { statuses[team] = "완료"; tasks[team] = taskText(team, "done", name); });
      statuses.qa = "결재 대기";
      tasks.qa = "'" + name + "' 검수 반려 — 대표 확인 필요";
      return { statuses: statuses, tasks: tasks };
    }
    if (stage === "rejected") {
      TEAM_SEQ.slice(0, 4).forEach((team) => { statuses[team] = "완료"; tasks[team] = taskText(team, "done", name); });
      tasks.qa = "'" + name + "' 대표님 반려 처리";
      return { statuses: statuses, tasks: tasks };
    }
    if (stage === "done") {
      TEAM_SEQ.slice(0, 6).forEach((team) => { statuses[team] = "완료"; tasks[team] = taskText(team, "done", name); });
      statuses.cs = "작업 중";
      tasks.cs = taskText("cs", "working", name);
      return { statuses: statuses, tasks: tasks };
    }
    const index = STAGE_TEAM_INDEX[stage] || 0;
    TEAM_SEQ.slice(0, index).forEach((team) => { statuses[team] = "완료"; tasks[team] = taskText(team, "done", name); });
    const current = TEAM_SEQ[Math.min(index, TEAM_SEQ.length - 1)];
    statuses[current] = "작업 중";
    tasks[current] = taskText(current, "working", name);
    return { statuses: statuses, tasks: tasks };
  }

  function demoSpeech(runs, pending, active) {
    const staffOf = (team) => STAFF.find((s) => s.team === team) || STAFF[0];
    if (pending.length) {
      const s = staffOf("qa");
      return {
        speaker: "qa", name: s.name, slot: s.slot, kind: "approval",
        text: pending.length > 1 ? "대표님, 오늘 결재하실 건 " + pending.length + "건이에요." : "대표님, 오늘 결재하실 건 이거 하나예요."
      };
    }
    if (active) {
      const stage = active.stage || "md";
      const name = active.name || "신상품";
      if (stage === "blocked") {
        const s = staffOf("qa");
        return { speaker: "qa", name: s.name, slot: s.slot, kind: "alert", text: "'" + name + "' 검수에서 막혔어요. 대표님 확인 부탁드려요." };
      }
      if (stage === "done") {
        const s = staffOf("marketing");
        return { speaker: "marketing", name: s.name, slot: s.slot, kind: "done", text: "'" + name + "' 몰에 등록 끝났어요. 이제 광고만 남았습니다!" };
      }
      if (stage !== "approval" && stage !== "rejected") {
        const team = TEAM_SEQ[Math.min(STAGE_TEAM_INDEX[stage] || 0, TEAM_SEQ.length - 1)];
        const s = staffOf(team);
        return { speaker: team, name: s.name, slot: s.slot, kind: "working", text: "'" + name + "' " + (STAGE_LABELS[stage] || stage) + " 단계 진행 중이에요. 잠시만요!" };
      }
    }
    if (runs.length) {
      const s = staffOf("cs");
      return { speaker: "cs", name: s.name, slot: s.slot, kind: "idle", text: "대표님, 오늘 결재는 다 끝났어요. 새 상품 한 건 더 넣어볼까요?" };
    }
    const s = staffOf("md");
    return { speaker: "md", name: s.name, slot: s.slot, kind: "idle", text: "대표님, 오늘은 결재할 게 없어요. 새 상품 한 건 넣어볼까요?" };
  }

  function demoPipeline(active) {
    const steps = (states) => PIPE_STAGES.map((key, i) => ({ key: key, label: STAGE_LABELS[key], state: states[i] }));
    if (!active) return steps(PIPE_STAGES.map(() => "wait"));
    const stage = active.stage || "md";
    if (stage === "done") return steps(PIPE_STAGES.map(() => "done"));
    let doneUntil = { done: 7, rejected: 4 }[stage];
    if (doneUntil == null) doneUntil = (STAGE_TEAM_INDEX[stage] || 0) + 1;
    return steps(PIPE_STAGES.map((key, i) => (i < doneUntil ? "done" : i === doneUntil ? "active" : "wait")));
  }

  function demoOffice() {
    const runs = sortedRuns();
    const pending = runs.filter((r) => r.status === "awaiting_approval");
    const active = pending[0] || runs.find((r) => r.status === "running") || runs[0] || null;
    const st = teamStatus(active);
    const staff = STAFF.map((row) => Object.assign({}, row, { status: st.statuses[row.team], task: st.tasks[row.team] }));
    return {
      server_time: new Date().toISOString(),
      started_at: demo.startedAt,
      room: { title: "대표 승인 회의실", subtitle: "팀장 7명 · 대표 1명", active_workflow: active ? brief(active) : null },
      ceo: {
        name: CEO_ROW.name, role: CEO_ROW.role, avatar: CEO_ROW.avatar,
        hair: CEO_ROW.hair, shirt: CEO_ROW.shirt, pants: CEO_ROW.pants,
        status: pending.length ? "결재 대기" : "대기 중"
      },
      staff: staff,
      counts: {
        teams: staff.length,
        pending_approval: pending.length,
        total_runs: runs.length,
        working: staff.filter((s) => s.status === "작업 중").length,
        awaiting_approval: staff.filter((s) => s.status === "결재 대기").length,
        done: staff.filter((s) => s.status === "완료").length,
        idle: staff.filter((s) => s.status === "대기 중").length
      },
      speech: demoSpeech(runs, pending, active),
      pipeline: demoPipeline(active),
      pending_approvals: pending.map(brief),
      activity: demo.activity.slice(-14).reverse(),
      salary_total: STAFF.reduce((sum, row) => sum + (row.salary_monthly || 0), 0)
    };
  }

  function demoWf() {
    const runs = sortedRuns();
    const pending = runs.filter((r) => r.status === "awaiting_approval");
    const scores = runs.map((r) => r.qa_score).filter((v) => typeof v === "number");
    return {
      count: runs.length,
      pending_approval: pending.length,
      completed: runs.filter((r) => r.status === "completed").length,
      blocked: runs.filter((r) => r.status === "qa_blocked").length,
      average_qa_score: scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length * 10) / 10 : null,
      stage_order: ["md", "design", "content", "qa", "approval", "dev", "marketing", "done"],
      stage_labels: STAGE_LABELS,
      workflows: runs,
      pending: pending
    };
  }

  function demoTick() {
    state.office = demoOffice();
    state.wf = demoWf();
    renderAll();
  }

  function demoClearSigs() {
    ["#people", "#activityFeed", "#roster", "#runs", "#decided", "#approvals"].forEach((sel) => {
      const el = $(sel);
      if (el) el.dataset.sig = "";
    });
  }

  /* ── 7개 팀 · 32개 도구 카탈로그 (app/teams 실제 목록) ── */
  const DEMO_CATALOG = (function () {
    const teams = [
      {
        team: "md", role: "MD(상품기획)",
        tools: ["md_price_quote", "md_size_curve", "md_allocate_initial_order", "md_reorder_signal", "md_sourcing_plan"],
        prompt: { preview: "공급가·몰 수수료·PG 수수료·무료배송 원가·부가세·반품충당금을 모두 얹고도 남는 판매가를 역산하고, 컬러×사이즈 초도 발주와 리오더 시점을 정합니다." }
      },
      {
        team: "design", role: "디자인(아트디렉터)",
        tools: ["ds_detail_blueprint", "ds_asset_spec", "ds_image_prompt", "ds_palette"],
        prompt: { preview: "상세페이지 섹션 블루프린트, 썸네일·배너·룩북 규격, 한국 남성 모델 이미지 프롬프트, 상품 컬러 기반 팔레트와 WCAG 대비까지 확정합니다." }
      },
      {
        team: "content", role: "콘텐츠(카피라이터)",
        tools: ["cn_seo_title", "cn_fit_guide", "cn_care_guide", "cn_disclosure", "cn_shortform_script", "cn_hashtags"],
        prompt: { preview: "50자 이내 SEO 제목, 핏·소재·코디 카피, 전자상거래법 고시정보, 릴스 15~30초 대본, 해시태그 10개를 만듭니다." }
      },
      {
        team: "qa", role: "검수(QA)",
        tools: ["qa_scan_claims", "qa_margin_guard", "qa_disclosure_guard", "qa_asset_guard"],
        prompt: { preview: "표시광고법 금지 표현(최고·완판·보장), 역마진·최소 마진 미달, 고시정보 누락, 이미지 규격을 규칙으로 검사하고 근거 조항과 함께 반려합니다." }
      },
      {
        team: "dev", role: "개발(몰 등록·재고)",
        tools: ["dev_option_matrix", "dev_product_payload", "dev_stock_alert"],
        prompt: { preview: "컬러×사이즈 옵션 매트릭스와 SKU 코드, 몰 등록 payload, 재고 동기화·소진 알림까지 처리합니다. 배포 전에는 대표 승인 없이 실행하지 않습니다." }
      },
      {
        team: "marketing", role: "마케팅(퍼포먼스)",
        tools: ["mk_budget_split", "mk_roas_break_even", "mk_ad_hooks", "mk_targeting"],
        prompt: { preview: "일 예산 채널 배분, 손익분기 ROAS 계산, 메타·네이버 광고 훅, 타겟 세그먼트를 설계하고 14일 스케줄로 세팅합니다." }
      },
      {
        team: "cs", role: "CS·운영",
        tools: ["cs_size_chart", "cs_exchange_guide", "cs_return_quote", "cs_shipping_delay_notice", "cs_defect_intake", "cs_escalation_decision"],
        prompt: { preview: "사이즈 추천, 교환·반품 배송비 판정, 배송 지연 공지, 불량 접수, 대표 보고 기준까지 응대 템플릿으로 만듭니다." }
      }
    ];
    const tools = [];
    teams.forEach((team) => team.tools.forEach((name) => tools.push({ name: name, team: team.team })));
    return { teams: teams, tools: tools };
  })();

  /* ── 샘플 상품 (app/web/index.html과 동일) ── */
  const DEMO_SAMPLE = {
    sku: "MN-OUT-2611-001",
    name: "에어 턴 오버핏 바람막이",
    category: "남성 아우터 > 바람막이",
    fit: "oversized",
    material: "폴리에스터 100%",
    color_options: ["블랙", "차콜", "아이보리"],
    size_options: ["M", "L", "XL", "2XL"],
    cost_price: 21000,
    stock: 45,
    supplier: "동대문 A도매",
    keywords: ["남자 바람막이", "오버핏 아우터"],
    country_of_origin: "베트남",
    description: "가을·초겨울 남성 오버핏 바람막이. 안감 메쉬, 밴딩 소매."
  };

  function seedDemo() {
    demo.workflows = [];
    demo.activity = [];
    demo.startedAt = new Date().toISOString();
    const t0 = Date.now();
    const at = (minutes) => new Date(t0 - minutes * 60000).toISOString();
    demoLog("🖥️ 라이브 오피스 가동 — 팀장 7명 접속 완료", "orchestrator", "system", at(12));
    demoLog("☕ 회의실 정리 완료 — 대표님 오시면 바로 시작합니다", "cs", "system", at(10));
    const rec = buildRecord(Object.assign({}, DEMO_SAMPLE, { note: "샘플 상품 런칭" }), at(7));
    demoLog("🎬 새 상품 런칭 — '" + rec.name + "' · 사입 " + fmt(rec.cost_price) + "원 · " + rec.inventory.stock + "장", "orchestrator", "start", at(7));
    demoLog("판매가 " + fmt(rec.selling_price) + "원 · 순이익 " + fmt(rec.net_profit) + "원 · 순이익률 " + (rec.margin_rate * 100).toFixed(1) + "% (" + rec._quote.basis + ")", "md", "log", at(6.2));
    demoLog("레이아웃 6개 섹션 / 에셋 4종 규격 확정 (모바일 860px, 대비 7.2:1)", "design", "log", at(5.4));
    demoLog("카피 완료 — 제목 " + rec.content.seo_title.length + "자 / 해시태그 " + rec.content.hashtags.length + "개 / 고시정보 누락 0건", "content", "log", at(4.6));
    demoLog("1차 검수 — 통과 (점수 " + rec.qa_score + ") 표시광고법·마진·고시정보·에셋 확인", "qa", "log", at(3.8));
    demoLog("📋 오늘 결재 대기 1건 — 대표님 승인만 남았습니다", "orchestrator", "system", at(3));
    demo.workflows.push(rec);
  }

  const LAUNCH_STEPS = [
    { stage: "md", team: "md", msg: (rec) => "판매가 " + fmt(rec.selling_price) + "원 · 순이익 " + fmt(rec.net_profit) + "원 · 순이익률 " + (rec.margin_rate * 100).toFixed(1) + "% (" + rec._quote.basis + ")" },
    { stage: "design", team: "design", msg: () => "레이아웃 6개 섹션 / 에셋 4종 규격 확정 (모바일 860px)" },
    { stage: "content", team: "content", msg: (rec) => "카피 완료 — 제목 " + rec.content.seo_title.length + "자 / 해시태그 " + rec.content.hashtags.length + "개" },
    { stage: "qa", team: "qa", msg: (rec) => "검수 " + (rec._qa.passed ? "통과" : "반려") + " (점수 " + rec.qa_score + ") — " + rec._qa.checks.length + "개 항목 확인" }
  ];

  async function demoLaunch(product) {
    const rec = buildRecord(product, new Date().toISOString());
    rec.status = "running";
    rec.stage = "md";
    rec.stage_label = STAGE_LABELS.md;
    rec.progress = STAGE_PROGRESS.md;
    rec.approval = null;
    demo.workflows.unshift(rec);
    demoLog("🎬 새 상품 런칭 — '" + rec.name + "' · 사입 " + fmt(rec.cost_price) + "원 · " + rec.inventory.stock + "장", "orchestrator", "start");
    demoTick();
    for (let i = 0; i < LAUNCH_STEPS.length; i++) {
      const step = LAUNCH_STEPS[i];
      rec.stage = step.stage;
      rec.stage_label = STAGE_LABELS[step.stage];
      rec.progress = STAGE_PROGRESS[step.stage];
      demoLog(step.msg(rec), step.team, "log");
      demoTick();
      await sleep(1000);
    }
    if (rec._qa.passed) {
      rec.status = "awaiting_approval";
      rec.stage = "approval";
      rec.stage_label = STAGE_LABELS.approval;
      rec.progress = STAGE_PROGRESS.approval;
      rec.approval = demoApproval(rec);
      demoLog("📋 결재 대기 — '" + rec.name + "' 검수 " + rec.qa_score + "점 · 판매가 " + fmt(rec.selling_price) + "원 · 순이익률 " + (rec.margin_rate * 100).toFixed(1) + "%", "orchestrator", "system");
    } else {
      rec.status = "qa_blocked";
      rec.stage = "blocked";
      rec.stage_label = STAGE_LABELS.blocked;
      rec.progress = STAGE_PROGRESS.blocked;
      demoLog("🚫 검수에서 막혔습니다 — " + (rec.qa_feedback[0] || "확인 필요"), "qa", "log");
    }
    rec.updated_at = new Date().toISOString();
    demoTick();
    return {
      workflow_id: rec.workflow_id,
      status: rec.status,
      awaiting_approval: rec._qa.passed,
      qa_report: { passed: rec._qa.passed, score: rec.qa_score, feedback: rec.qa_feedback },
      result: {}
    };
  }

  async function demoDecide(workflowId, approved, note) {
    const rec = demo.workflows.find((r) => r.workflow_id === workflowId);
    if (!rec) throw new Error("워크플로를 찾을 수 없습니다: " + workflowId);
    if (rec.status !== "awaiting_approval") throw new Error("승인 대기 상태가 아닙니다 (이미 종료되었거나 실행 중)");
    const now = new Date().toISOString();
    rec.approval = Object.assign({}, rec.approval, {
      status: approved ? "approved" : "rejected",
      decided_at: now,
      decided_by: "대표",
      note: note || ""
    });
    demoLog((approved ? "✅" : "🚫") + " 대표님 " + (approved ? "승인" : "반려") + " — '" + rec.name + "'" + (note ? " / 메모: " + note : ""), "approval", "decision");
    if (!approved) {
      rec.status = "rejected";
      rec.stage = "rejected";
      rec.stage_label = STAGE_LABELS.rejected;
      rec.progress = STAGE_PROGRESS.rejected;
      rec.updated_at = now;
      demoTick();
      return { workflow_id: workflowId, status: "rejected", result: {} };
    }
    rec.status = "running";
    rec.stage = "dev";
    rec.stage_label = STAGE_LABELS.dev;
    rec.progress = STAGE_PROGRESS.dev;
    demoTick();
    await sleep(800);
    const mallId = "MN" + String(Date.now()).slice(-8);
    rec.deployed = {
      deployed: true, simulated: true, platform: "custom", mall_product_id: mallId,
      product_url: null, inventory_synced: true, errors: [], deployed_at: new Date().toISOString()
    };
    demoLog("상품 등록 완료 — custom / ID " + mallId + " / 재고 동기화 true (시뮬레이션)", "dev", "log");
    demoTick();
    await sleep(800);
    const daily = Math.max(10000, Math.round(rec.net_profit * 0.6 / 1000) * 1000);
    rec.stage = "marketing";
    rec.stage_label = STAGE_LABELS.marketing;
    rec.progress = STAGE_PROGRESS.marketing;
    demoLog("캠페인 세팅 완료 — 메타·네이버·인스타 3채널 / 14일 예산 " + fmt(daily * 14) + "원 (일 " + fmt(daily) + "원)", "marketing", "log");
    demoTick();
    await sleep(900);
    rec.status = "completed";
    rec.stage = "done";
    rec.stage_label = STAGE_LABELS.done;
    rec.progress = 100;
    rec.updated_at = new Date().toISOString();
    demoLog("🏁 '" + rec.name + "' 런칭 완료 — 몰 등록·광고 세팅·CS 템플릿까지 끝났습니다", "orchestrator", "system");
    demoTick();
    return { workflow_id: workflowId, status: "completed", result: {} };
  }

  async function demoApi(path, opts) {
    const method = (opts && opts.method) || "GET";
    const body = opts && opts.body ? JSON.parse(opts.body) : null;
    if (path === "/office/state") { await sleep(40); return demoOffice(); }
    if (path === "/workflows") { await sleep(40); return demoWf(); }
    if (path === "/teams/catalog") return DEMO_CATALOG;
    if (path === "/health") {
      return {
        status: "ok", app: "남성 보세몰 AI 직원 시스템", version: "0.1.0-demo", env: "browser",
        llm_provider: "데모(브라우저)", mall_platform: "custom(시뮬레이션)", workflows: demo.workflows.length
      };
    }
    if (path === "/workflows/launch" && method === "POST") return demoLaunch(body.product);
    const match = /^\/workflows\/([^/]+)\/approval$/.exec(path);
    if (match && method === "POST") return demoDecide(decodeURIComponent(match[1]), Boolean(body.approved), body.note || "");
    throw new Error("데모에서 지원하지 않는 경로입니다: " + path);
  }
