"""Browser acceptance test. Run: uv run --with playwright python examples/test_showcase.py"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root / "examples/showcase.py")], cwd=root, check=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto((root / "docs/showcase/index.html").as_uri())
        expect(page.get_by_role("heading", name="Remember. Correct. Respect.")).to_be_visible()
        expect(page.locator("article")).to_have_count(6)
        receipt = page.locator("article").nth(3)
        receipt.get_by_text("Inspect SDK receipt & evidence").click()
        expect(receipt.locator("pre")).to_contain_text('"outcome": "protected_by_user"')
        expect(receipt.locator("pre")).to_contain_text("Home city: Boston")
        expect(receipt.locator("pre")).to_contain_text("user:correction-1")
        data = json.loads((root / "docs/showcase/memory.json").read_text())
        assert data["other_user_messages"] == data["active_after_forget"] == 0
        assert data["steps"][-1]["result"]["outcome"] == "blocked_by_forget"
        receipt.get_by_text("Inspect SDK receipt & evidence").click()
        screenshots = root / "docs/screenshots"
        screenshots.mkdir(exist_ok=True)
        page.screenshot(path=str(screenshots / "memory-lifecycle.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert errors == []
        browser.close()
    print("Browser acceptance passed: memory-lifecycle")


if __name__ == "__main__":
    main()
