from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.schema.shared import FaqAnswer, FaqLanguage, InquiryTopic, InstantAnswerRequest

SERVICE = "app.services.shared.faq_answer_service"
QUESTION = "Do I have to pay to enter the lottery?"

# Every test that reaches _ask_claude patches _client: the real one is built from .env's key, so
# an unpatched call would be a real, billed API request.


def make_request(content=QUESTION, lang=FaqLanguage.en):
    return InstantAnswerRequest(topic=InquiryTopic.lottery, content=content, lang=lang)


def configure(mock_settings, key="test-key", debug=False):
    mock_settings.ANTHROPIC_API_KEY = key
    mock_settings.DEBUG = debug


def make_response(stop_reason="end_turn", parsed=None):
    response = MagicMock()
    response.stop_reason = stop_reason
    response.parsed_output = parsed
    return response

# ───────────────────────────────────────────────────────────────
# When Claude is (not) called
# ───────────────────────────────────────────────────────────────

class TestFaqAnswerGuards:

    @patch(f"{SERVICE}._ask_claude")
    @patch(f"{SERVICE}.settings")
    def test_without_api_key_the_model_is_never_called(self, mock_settings, mock_ask):
        from app.services.shared.faq_answer_service import FaqAnswerService

        configure(mock_settings, key=None)

        result = FaqAnswerService.answer(make_request())

        assert result.answerable is False
        assert result.answer is None
        mock_ask.assert_not_called()

    @patch(f"{SERVICE}._ask_claude")
    @patch(f"{SERVICE}.settings")
    def test_debug_mode_never_calls_the_model(self, mock_settings, mock_ask):
        from app.services.shared.faq_answer_service import FaqAnswerService

        configure(mock_settings, debug=True)

        result = FaqAnswerService.answer(make_request())

        assert result.answerable is False
        mock_ask.assert_not_called()

# ───────────────────────────────────────────────────────────────
# Turning the model's result into the API response
# ───────────────────────────────────────────────────────────────

class TestFaqAnswerService:

    @patch(f"{SERVICE}._ask_claude")
    @patch(f"{SERVICE}.settings")
    def test_answerable_question_returns_answer(self, mock_settings, mock_ask):
        from app.services.shared.faq_answer_service import FaqAnswerService

        configure(mock_settings)
        mock_ask.return_value = FaqAnswer(answerable_from_faq=True, answer="  No, entering is free.  ")

        result = FaqAnswerService.answer(make_request())

        assert result.answerable is True
        assert result.answer == "No, entering is free."

    @patch(f"{SERVICE}._ask_claude")
    @patch(f"{SERVICE}.settings")
    def test_question_outside_faq_is_not_answerable(self, mock_settings, mock_ask):
        from app.services.shared.faq_answer_service import FaqAnswerService

        configure(mock_settings)
        mock_ask.return_value = FaqAnswer(answerable_from_faq=False, answer="")

        result = FaqAnswerService.answer(make_request())

        assert result.answerable is False
        assert result.answer is None

    @patch(f"{SERVICE}._ask_claude")
    @patch(f"{SERVICE}.settings")
    def test_answerable_flag_with_empty_answer_is_not_answerable(self, mock_settings, mock_ask):
        from app.services.shared.faq_answer_service import FaqAnswerService

        configure(mock_settings)
        mock_ask.return_value = FaqAnswer(answerable_from_faq=True, answer="   ")

        assert FaqAnswerService.answer(make_request()).answerable is False

    @patch(f"{SERVICE}._ask_claude")
    @patch(f"{SERVICE}.settings")
    def test_no_result_is_not_answerable(self, mock_settings, mock_ask):
        from app.services.shared.faq_answer_service import FaqAnswerService

        configure(mock_settings)
        mock_ask.return_value = None

        assert FaqAnswerService.answer(make_request()).answerable is False

    @patch(f"{SERVICE}._client")
    @patch(f"{SERVICE}.settings")
    def test_api_error_degrades_instead_of_raising(self, mock_settings, mock_client):
        from app.services.shared.faq_answer_service import FaqAnswerService

        configure(mock_settings)
        mock_client.messages.parse.side_effect = TimeoutError("upstream timed out")

        assert FaqAnswerService.answer(make_request()).answerable is False

# ───────────────────────────────────────────────────────────────
# The Claude call itself (fake client, no network)
# ───────────────────────────────────────────────────────────────

class TestAskClaude:

    @patch(f"{SERVICE}._client")
    def test_request_shape(self, mock_client):
        from app.services.shared.faq_answer_service import MODEL, _ask_claude

        mock_client.messages.parse.return_value = make_response(
            parsed=FaqAnswer(answerable_from_faq=True, answer="Free.")
        )

        _ask_claude(InquiryTopic.lottery, QUESTION, "FAQ TEXT")

        kwargs = mock_client.messages.parse.call_args.kwargs
        assert kwargs["model"] == MODEL == "claude-haiku-4-5"
        assert "<faq>\nFAQ TEXT\n</faq>" in kwargs["system"]
        assert not kwargs["system"].startswith('"')
        assert "output_config" not in kwargs  # Haiku 4.5 rejects `effort`
        assert kwargs["output_format"] is FaqAnswer
        assert f"<question>\n{QUESTION}\n</question>" in kwargs["messages"][0]["content"]

    @patch(f"{SERVICE}._client")
    def test_returns_parsed_output(self, mock_client):
        from app.services.shared.faq_answer_service import _ask_claude

        parsed = FaqAnswer(answerable_from_faq=True, answer="Free.")
        mock_client.messages.parse.return_value = make_response(parsed=parsed)

        assert _ask_claude(InquiryTopic.lottery, QUESTION, "FAQ") is parsed

    @pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
    @patch(f"{SERVICE}._client")
    def test_refusal_or_cut_off_returns_none(self, mock_client, stop_reason):
        from app.services.shared.faq_answer_service import _ask_claude

        mock_client.messages.parse.return_value = make_response(stop_reason=stop_reason)

        assert _ask_claude(InquiryTopic.lottery, QUESTION, "FAQ") is None

# ───────────────────────────────────────────────────────────────
# FAQ files and request validation
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

        configure(mock_settings)
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
