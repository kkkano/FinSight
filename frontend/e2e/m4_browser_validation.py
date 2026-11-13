"""回放真实核查产物验证界面；不替代线上研究问题验收。"""
import hashlib
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from m6_browser_validation import install_routes, colors, contrast

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "frontend/test-results/m4-native"
INPUT = ROOT / "tests/agent_eval/results/m4_step5_review_measurement.json"

SEED = """async ({row, dark}) => {
  const { useStore } = await import('/src/store/useStore.ts');
  const { useModelSelectionStore } = await import('/src/store/modelSelection.ts');
  useModelSelectionStore.setState({ metadata: { id: 'system:qa', label: '界面验收模型', native_tool_calls: true,
    supports_tools: true, capability_status: 'supported' } });
  useStore.getState().setTheme(dark ? 'dark' : 'light');
  useStore.setState({ showRightPanel: false, isChatLoading: false, messages: [
    { id: 'review-user', role: 'user', content: row.query, timestamp: Date.now() - 2000 },
    { id: 'review-message', role: 'assistant', content: row.answer, runId: 'review-ui-run',
      timestamp: Date.now() - 1000, runStatus: 'completed', persistenceStatus: 'saved', isLoading: false,
      blocks: [{ id: 'review-body', kind: 'text', content: row.answer, content_phase: 'answer', revision: 0 },
        { id: row.review.review_id, kind: 'review', review: row.review, revision: 1 }] }
  ] });
  window.__reviewRequests = [];
  const priorFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    if (String(input).endsWith('/api/execute') && init?.method === 'POST') window.__reviewRequests.push(JSON.parse(init.body));
    return priorFetch(input, init);
  };
}"""


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rows = json.loads(INPUT.read_text(encoding="utf-8"))["rows"]
    row = next(item for item in rows if item["variant"] == "injected" and item["review"].get("findings"))
    evidence = {"scope": "本机真实核查产物回放；修订请求网络边界为协议夹具，不是线上验收。",
        "input_sha256": hashlib.sha256(INPUT.read_bytes()).hexdigest(), "checks": [], "screenshots": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        try:
            for dark, width in [(False, 1440), (True, 1440), (False, 390), (True, 390)]:
                context = browser.new_context(viewport={"width": width, "height": 960}, reduced_motion="reduce", service_workers="block")
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                install_routes(page, dark)
                page.goto("http://127.0.0.1:4273/chat")
                page.wait_for_load_state("networkidle")
                expect(page.locator("#chat-input")).to_be_visible()
                evidence["initial_dom"] = page.locator("body").aria_snapshot()[:1200]
                page.evaluate(SEED, {"row": row, "dark": dark})
                review = page.locator("[data-review-id]")
                expect(review.get_by_text("有待确认的内容", exact=True)).to_be_visible()
                expect(page.locator(".fs-prose mark").first).to_be_visible()
                mark_color = page.locator(".fs-prose mark").first.evaluate("node => getComputedStyle(node).color")
                mark_contrast = contrast(mark_color, colors(page)["bg"])
                assert mark_contrast >= 4.5, {"mark_color": mark_color, "contrast": mark_contrast}
                expect(review.locator("blockquote")).to_have_text(row["review"]["findings"][0]["quote"])
                review.scroll_into_view_if_needed()
                name = ("dark" if dark else "light") + "-" + str(width) + ".png"
                page.screenshot(path=str(OUTPUT / name), full_page=True)
                evidence["screenshots"].append(name)
                review.get_by_role("button", name="按核查意见修订", exact=True).click()
                page.wait_for_function("window.__reviewRequests.length === 1")
                request = page.evaluate("window.__reviewRequests[0]")
                assert request["review_revision"]["answer"] == row["answer"]
                assert request["review_revision"]["findings"] == row["review"]["findings"]
                assert request["resume_from_run_id"] == "review-ui-run"
                original = page.evaluate("async () => (await import('/src/store/useStore.ts')).useStore.getState().messages.find(x => x.id === 'review-message').content")
                assert original == row["answer"]
                assert not errors, errors
                evidence["checks"].append({"dark": dark, "width": width, "quote_highlight": True,
                    "revision_post": True, "original_preserved": True, "mark_contrast": mark_contrast, "page_errors": errors})
                context.close()
        finally:
            browser.close()
    (OUTPUT / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"checks_passed": len(evidence["checks"]), "evidence": str(OUTPUT / "evidence.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
