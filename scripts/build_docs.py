#!/usr/bin/env python3
"""app/web/index.html(로컬 FastAPI용) → docs/index.html(GitHub Pages 정적 데모용) 생성."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "app" / "web" / "index.html"
ENGINE = ROOT / "scripts" / "demo_engine.js"
OUT = ROOT / "docs" / "index.html"

html = SRC.read_text(encoding="utf-8")
engine = ENGINE.read_text(encoding="utf-8")


def swap(old: str, new: str, label: str) -> None:
    global html
    assert html.count(old) == 1, f"{label}: {html.count(old)} matches"
    html = html.replace(old, new)


# ── 1) CSS: 데모 모드 스타일 ───────────────────────────────────────────
CSS = """
/* ── 데모 모드 (정적 호스팅) ── */
.net.demo i{background:var(--butter)}
.demo-strip{
  border:2.5px solid var(--line);border-radius:10px;background:#fff6e0;
  box-shadow:2px 2px 0 rgba(47,35,40,.12);
  padding:7px 10px;margin:0 0 10px;font-size:9.5px;line-height:1.55;
  font-weight:700;color:#8a6a1f;text-align:center;
}
.demo-strip b{color:#b4614f}
"""
swap("@keyframes bob{", CSS + "\n@keyframes bob{", "css")

# ── 2) 상단 데모 안내 띠 ─────────────────────────────────────────────
swap(
    '<div class="wrap">\n\n  <!-- ══════════ TAB 1 · 라이브 오피스 ══════════ -->',
    '<div class="wrap">\n\n  <div class="demo-strip hidden" id="demoStrip">'
    "🧪 <b>브라우저 데모</b> — 실제 LLM·몰 등록·광고 집행 없이 화면과 승인 흐름만 재현합니다. "
    "승인·반려는 이 브라우저 안에서만 반영됩니다.</div>\n\n"
    "  <!-- ══════════ TAB 1 · 라이브 오피스 ══════════ -->",
    "demo strip",
)

# ── 3) 대시보드: 데모 초기화 버튼 ────────────────────────────────────
swap(
    '        <div class="launch-status" id="launchStatus"></div>',
    '        <div class="launch-status" id="launchStatus"></div>\n'
    '        <div id="demoTools" class="hidden">\n'
    '          <button class="btn ghost" id="demoReset">🔄 데모 초기화 — 샘플 상태로</button>\n'
    "        </div>",
    "reset button",
)

# ── 4) api(): 정적 호스팅에서는 데모 엔진으로 위임 ───────────────────
swap(
    """  async function api(path, opts) {
    const options = Object.assign({ headers: { "Content-Type": "application/json" } }, opts || {});""",
    """  async function api(path, opts) {
    if (DEMO_MODE) return demoApi(path, opts);
    const options = Object.assign({ headers: { "Content-Type": "application/json" } }, opts || {});""",
    "api dispatch",
)

# ── 5) setNet(): 데모 모드 표기 ───────────────────────────────────────
swap(
    '    $("#netText").textContent = ok ? "서버 연결됨" : "연결 끊김";',
    '    $("#netText").textContent = ok ? (DEMO_MODE ? "데모 모드" : "서버 연결됨") : "연결 끊김";',
    "setNet",
)

# ── 6) 데모 엔진 삽입 (setNet 뒤, 상태 라벨 앞) ──────────────────────
MARKER = "  /* ────────────── 상태 라벨 ────────────── */"
swap(MARKER, engine + "\n" + MARKER, "engine insert")

# ── 7) 시작 시퀀스: 데모면 시드 + 안내 노출 ──────────────────────────
swap(
    """  /* ────────────── 시작 ────────────── */
  tickClock();""",
    """  /* ────────────── 시작 ────────────── */
  if (DEMO_MODE) {
    seedDemo();
    $("#net").classList.add("demo");
    $("#netText").textContent = "데모 모드";
    $("#demoStrip").classList.remove("hidden");
    $("#demoTools").classList.remove("hidden");
    $("#demoReset").addEventListener("click", () => {
      if (state.busy) return;
      seedDemo();
      demoClearSigs();
      demoTick();
      goTab("office");
      toast("🔄 데모를 처음 상태로 되돌렸어요", "good");
    });
  }
  tickClock();""",
    "init block",
)

assert "/* 상태 라벨 */" not in html
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(html, encoding="utf-8")
print(f"wrote {OUT} ({len(html):,} bytes)")
