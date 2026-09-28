from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.schema.shared import FaqAnswer, FaqLanguage, InquiryTopic, InstantAnswerRequest

SERVICE = "app.services.shared.faq_answer_service"
QUESTION = "Do I have to pay to enter the lottery?"


def make_request(content=QUESTION, lang=FaqLanguage.en):
    return InstantAnswerRequest(topic=InquiryTopic.lottery, content=content, lang=lang)

# ───────────────────────────────────────────────────────────────
# FAQ Answer Service Tests
# ───────────────────────────────────────────────────────────────

class TestFaqAnswerService:

    @patch(f"{SERVICE}._ask_claude")
    @patch(f"{SERVICE}.settings")
    def test_without_api_key_the_model_is_never_called(self, mock_settings, mock_ask):
        from app.services.shared.faq_answer_service import FaqAnswerService

        mock_settings.ANTHROPIC_API_KEY = None

        result = FaqAnswerService.answer(make_request())

        assert result.answerable is False
        assert result.answer is None
        mock_ask.assert_not_called()

    @patch(f"{SERVICE}._ask_claude")
    @patch(f"{SERVICE}.settings")
    def test_answerable_question_returns_answer(self, mock_settings, mock_ask):
        from app.services.shared.faq_answer_service import FaqAnswerService

        mock_settings.ANTHROPIC_API_KEY = "test-key"
        mock_ask.return_value = FaqAnswer(answerable_from_faq=True, answer="  No, entering is free.  ")

        result = FaqAnswerService.answer(make_request())

        assert result.answerable is True
        assert result.answer == "No, entering is free."

    @patch(f"{SERVICE}._ask_claude")
    @patch(f"{SERVICE}.settings")
    def test_question_outside_faq_is_not_answerable(self, mock_settings, mock_ask):
        from app.services.shared.faq_answer_service import FaqAnswerService

        mock_settings.ANTHROPIC_API_KEY = "test-key"
        mock_ask.return_value = FaqAnswer(answerable_from_faq=False, answer="")

        result = FaqAnswerService.answer(make_request())

        assert result.answerable is False
        assert result.answer is None

    @patch(f"{SERVICE}._ask_claude")
    @patch(f"{SERVICE}.settings")
    def test_answerable_flag_with_empty_answer_is_not_answerable(self, mock_settings, mock_ask):
        from app.services.shared.faq_answer_service import FaqAnswerService

        mock_settings.ANTHROPIC_API_KEY = "test-key"
        mock_ask.return_value = FaqAnswer(answerable_from_faq=True, answer="   ")

        assert FaqAnswerService.answer(make_request()).answerable is False

    @patch(f"{SERVICE}._ask_claude")
    @patch(f"{SERVICE}.settings")
    def test_refusal_is_not_answerable(self, mock_settings, mock_ask):
        from app.services.shared.faq_answer_service import FaqAnswerService

        mock_settings.ANTHROPIC_API_KEY = "test-key"
        mock_ask.return_value = None

        assert FaqAnswerService.answer(make_request()).answerable is False

    @patch(f"{SERVICE}._ask_claude")
    @patch(f"{SERVICE}.settings")
    def test_api_error_degrades_instead_of_raising(self, mock_settings, mock_ask):
        from app.services.shared.faq_answer_service import FaqAnswerService

        mock_settings.ANTHROPIC_API_KEY = "test-key"
        mock_ask.side_effect = TimeoutError("upstream timed out")

        assert FaqAnswerService.answer(make_request()).answerable is False

    @patch(f"{SERVICE}.settings")
    def test_unimplemented_call_degrades_instead_of_raising(self, mock_settings):
        from app.services.shared.faq_answer_service import FaqAnswerService

        mock_settings.ANTHROPIC_API_KEY = "test-key"

        assert FaqAnswerService.answer(make_request()).answerable is False

# ───────────────────────────────────────────────────────────────
# FAQ file and request validation
# ───────────────────────────────────────────────────────────────

class TestFaqContent:

    @pytest.mark.parametrize("lang, heading", [
        (FaqLanguage.en, "# Frequently asked questions"),
        (FaqLanguage.ja, "# よくあるご質問"),
    ])
    def test_faq_loads_without_maintainer_comments(self, lang, heading):
        from app.services.shared.faq_answer_service import load_faq

        faq = load_faq(lang)

        assert heading in faq
        assert "<!--" not in faq
        assert "TODO" not in faq

    @patch(f"{SERVICE}._ask_claude")
    @patch(f"{SERVICE}.settings")
    def test_lang_selects_the_faq_file(self, mock_settings, mock_ask):
        from app.services.shared.faq_answer_service import FaqAnswerService

        mock_settings.ANTHROPIC_API_KEY = "test-key"
        mock_ask.return_value = None

        FaqAnswerService.answer(make_request(content="抽選は無料ですか？", lang=FaqLanguage.ja))

        faq_sent = mock_ask.call_args.args[2]
        assert "# よくあるご質問" in faq_sent

    def test_lang_defaults_to_english(self):
        assert make_request().lang == FaqLanguage.en

    def test_short_japanese_question_accepted(self):
        assert make_request(content="返金できますか？").content == "返金できますか？"

    def test_short_question_rejected(self):
        with pytest.raises(ValidationError):
            make_request(content="   hi   ")

    def test_full_width_spaces_only_rejected(self):
        with pytest.raises(ValidationError):
            make_request(content="　" * 20)
