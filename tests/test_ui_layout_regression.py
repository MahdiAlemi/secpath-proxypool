from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UILayoutRegressionTest(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_hidden_attribute_always_removes_inactive_detail_states(self) -> None:
        base = self.read("dashboard/static/css/base.css")
        serving = self.read("dashboard/static/css/serving.css")
        validation = self.read("dashboard/static/css/validation.css")

        self.assertRegex(base, r"\[hidden\]\s*\{\s*display:\s*none\s*!important")
        self.assertIn(".serving-detail-empty[hidden],#serving-detail[hidden]", serving)
        self.assertIn(".validation-detail-empty[hidden],#validation-detail[hidden]", validation)

    def test_server_editor_has_bounded_scroll_regions(self) -> None:
        css = self.read("dashboard/static/css/serving.css")

        self.assertRegex(
            css,
            r"\.serving-editor-modal\{[^}]*display:flex;[^}]*flex-direction:column",
        )
        self.assertRegex(
            css,
            r"\.serving-editor-layout\{[^}]*flex:1 1 auto;[^}]*min-height:0",
        )
        self.assertRegex(
            css,
            r"\.serving-editor-form,\.serving-editor-preview\{[^}]*min-height:0;[^}]*overflow-y:auto",
        )
        self.assertIn("100dvh", css)

    def test_mobile_server_editor_uses_full_dynamic_viewport(self) -> None:
        css = self.read("dashboard/static/css/serving.css")
        self.assertIn("@media(max-width:760px){.modal:has(.serving-editor-modal){align-items:stretch;padding:0}", css)
        self.assertRegex(
            css,
            r"@media\(max-width:760px\)\{[^\n]*\.serving-editor-modal\{[^}]*height:100dvh",
        )

    def test_validation_editor_and_generic_modals_remain_scrollable(self) -> None:
        base = self.read("dashboard/static/css/base.css")
        validation = self.read("dashboard/static/css/validation.css")

        self.assertIn("overscroll-behavior: contain", base)
        self.assertIn("scrollbar-gutter: stable", base)
        self.assertIn("max-height:calc(100dvh - 24px)", validation)


if __name__ == "__main__":
    unittest.main()
