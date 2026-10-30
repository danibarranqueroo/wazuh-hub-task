import pytest

from wazuh_brief.config import Settings
from wazuh_brief.llm import ClaudeSummarizer, select_summarizer
from wazuh_brief.llm_claude_code import ClaudeCodeSummarizer


def settings(provider: str, key: str | None) -> Settings:
    return Settings(_env_file=None, llm_provider=provider, anthropic_api_key=key)


@pytest.mark.parametrize(
    ("provider", "key", "expected", "reason"),
    [
        ("auto", "sk-test", ClaudeSummarizer, None),
        ("auto", None, None, "ANTHROPIC_API_KEY is not set"),
        ("auto", "", None, "ANTHROPIC_API_KEY is not set"),
        ("anthropic", "sk-test", ClaudeSummarizer, None),
        ("anthropic", None, None, "LLM_PROVIDER is anthropic but ANTHROPIC_API_KEY is not set"),
        ("claude-code", None, ClaudeCodeSummarizer, None),
        ("claude-code", "sk-test", ClaudeCodeSummarizer, None),
        ("mock", "sk-test", None, "LLM_PROVIDER is mock"),
        ("mock", None, None, "LLM_PROVIDER is mock"),
    ],
)
def test_provider_matrix(provider, key, expected, reason):
    primary, why = select_summarizer(settings(provider, key))

    if expected is None:
        assert primary is None
    else:
        assert isinstance(primary, expected)
    assert why == reason


def test_auto_never_picks_claude_code():
    for key in (None, "", "sk-test"):
        primary, _ = select_summarizer(settings("auto", key))
        assert not isinstance(primary, ClaudeCodeSummarizer)


def test_claude_code_gets_a_longer_timeout():
    primary, _ = select_summarizer(settings("claude-code", None))
    assert primary._timeout >= 120


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError):
        settings("openai", None)
