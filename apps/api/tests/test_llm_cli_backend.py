"""The Claude CLI backend: argv construction, parsing, and backend dispatch.

These tests never spawn the real binary — ``subprocess.run`` is patched and the
recorded argv/stdin asserted instead. What matters here is that the harness-strip
flags are always present (without them a call carries ~50k tokens of coding-agent
preamble), that API-key env vars are removed so a stray key cannot silently
redirect billing to the API, and that ``LLM_BACKEND`` actually routes.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.services import llm_cli
from app.services.llm_cli import ClaudeCLIError
from app.services.structured_output import complete_text, request_tool_call

_TOOL = {
    "name": "submit_plan",
    "description": "Submit a plan.",
    "input_schema": {
        "type": "object",
        "properties": {"steps": {"type": "array", "items": {"type": "string"}}},
        "required": ["steps"],
    },
}


def _cli_payload(result: str, *, is_error: bool = False) -> str:
    return json.dumps(
        {
            "type": "result",
            "is_error": is_error,
            "result": result,
            "usage": {"input_tokens": 100, "output_tokens": 10},
            "duration_ms": 1200,
        }
    )


@pytest.fixture
def fake_run():
    """Patch subprocess.run and shutil.which; yield the run mock."""
    with (
        patch("app.services.llm_cli.shutil.which", return_value="/usr/local/bin/claude"),
        patch("app.services.llm_cli.subprocess.run") as run,
    ):
        run.return_value = MagicMock(returncode=0, stdout=_cli_payload("OK"), stderr="")
        yield run


@pytest.fixture
def cli_backend(monkeypatch):
    monkeypatch.setattr(settings, "LLM_BACKEND", "cli")


# ---------------------------------------------------------------------------
# argv construction
# ---------------------------------------------------------------------------


class TestInvocation:
    def test_strip_flags_always_present(self, fake_run):
        llm_cli.complete_text(model="claude-opus-5", system="S", messages=[], max_tokens=100)

        argv = fake_run.call_args.args[0]
        # Without these the CLI loads its full coding-agent harness.
        assert "--strict-mcp-config" in argv
        assert argv[argv.index("--setting-sources") + 1] == ""
        assert argv[argv.index("--tools") + 1] == ""
        assert argv[argv.index("--model") + 1] == "claude-opus-5"
        assert argv[argv.index("--output-format") + 1] == "json"

    def test_prompt_goes_over_stdin_not_argv(self, fake_run):
        big_prompt = "x" * 50_000
        llm_cli.complete_text(
            model="claude-opus-5",
            system="S",
            messages=[{"role": "user", "content": big_prompt}],
            max_tokens=100,
        )

        assert fake_run.call_args.kwargs["input"] == big_prompt
        assert big_prompt not in fake_run.call_args.args[0]

    def test_api_key_env_vars_are_stripped(self, fake_run, monkeypatch):
        # A stray key would make the CLI bill the API instead of the subscription.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-should-not-leak")

        llm_cli.complete_text(model="claude-opus-5", system="S", messages=[], max_tokens=100)

        child_env = fake_run.call_args.kwargs["env"]
        assert "ANTHROPIC_API_KEY" not in child_env
        assert "ANTHROPIC_AUTH_TOKEN" not in child_env

    def test_missing_binary_raises_clear_error(self):
        with patch("app.services.llm_cli.shutil.which", return_value=None):
            with pytest.raises(ClaudeCLIError, match="Claude CLI not found"):
                llm_cli.complete_text(model="m", system="S", messages=[], max_tokens=10)


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


class TestFailures:
    def test_nonzero_exit_raises(self, fake_run):
        fake_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
        with pytest.raises(ClaudeCLIError, match="exited 1"):
            llm_cli.complete_text(model="m", system="S", messages=[], max_tokens=10)

    def test_timeout_raises(self, fake_run):
        fake_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=300)
        with pytest.raises(ClaudeCLIError, match="timed out"):
            llm_cli.complete_text(model="m", system="S", messages=[], max_tokens=10)

    def test_error_result_raises(self, fake_run):
        fake_run.return_value = MagicMock(
            returncode=0, stdout=_cli_payload("rate limited", is_error=True), stderr=""
        )
        with pytest.raises(ClaudeCLIError, match="reported an error"):
            llm_cli.complete_text(model="m", system="S", messages=[], max_tokens=10)

    def test_non_json_stdout_raises(self, fake_run):
        fake_run.return_value = MagicMock(returncode=0, stdout="not json", stderr="")
        with pytest.raises(ClaudeCLIError, match="non-JSON"):
            llm_cli.complete_text(model="m", system="S", messages=[], max_tokens=10)


# ---------------------------------------------------------------------------
# Message flattening
# ---------------------------------------------------------------------------


class TestFlattening:
    def test_single_message_is_unlabelled(self):
        assert llm_cli._flatten_messages([{"role": "user", "content": "hi"}]) == "hi"

    def test_multi_turn_is_labelled(self):
        out = llm_cli._flatten_messages(
            [
                {"role": "user", "content": "q1"},
                {"role": "assistant", "content": "a1"},
            ]
        )
        assert "[user]\nq1" in out
        assert "[assistant]\na1" in out

    def test_tool_result_blocks_survive(self):
        # The cleaning planner feeds validator rejections back as tool_result;
        # dropping them would make the model retry with no feedback.
        out = llm_cli._flatten_messages(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "x", "content": "REJECTED: bad op"}
                    ],
                }
            ]
        )
        assert "REJECTED: bad op" in out

    def test_system_blocks_are_concatenated(self):
        text = llm_cli._system_to_text(
            [
                {"type": "text", "text": "A", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "B"},
            ]
        )
        assert "A" in text and "B" in text


# ---------------------------------------------------------------------------
# JSON extraction (stands in for forced tool use)
# ---------------------------------------------------------------------------


class TestJSONExtraction:
    @pytest.mark.parametrize(
        "raw",
        [
            '{"steps": ["a"]}',
            '```json\n{"steps": ["a"]}\n```',
            '```\n{"steps": ["a"]}\n```',
            'Here you go:\n{"steps": ["a"]}\nHope that helps!',
        ],
    )
    def test_extracts_from_common_shapes(self, raw):
        assert llm_cli._extract_json_object(raw) == {"steps": ["a"]}

    @pytest.mark.parametrize("raw", ["no json here", "", "[1, 2, 3]", "{broken"])
    def test_returns_none_when_unparseable(self, raw):
        assert llm_cli._extract_json_object(raw) is None

    def test_schema_is_rendered_into_system_prompt(self, fake_run):
        fake_run.return_value = MagicMock(
            returncode=0, stdout=_cli_payload('{"steps": []}'), stderr=""
        )
        llm_cli.request_tool_call(model="m", system="S", messages=[], tool=_TOOL, max_tokens=10)

        argv = fake_run.call_args.args[0]
        system_text = argv[argv.index("--system-prompt") + 1]
        assert "input_schema" not in system_text  # the schema body, not the key
        assert '"steps"' in system_text
        assert "REQUIRED OUTPUT FORMAT" in system_text

    def test_retries_then_succeeds_on_unparseable_first_reply(self, fake_run):
        fake_run.side_effect = [
            MagicMock(returncode=0, stdout=_cli_payload("I cannot do that"), stderr=""),
            MagicMock(returncode=0, stdout=_cli_payload('{"steps": ["a"]}'), stderr=""),
        ]
        result = llm_cli.request_tool_call(
            model="m", system="S", messages=[], tool=_TOOL, max_tokens=10
        )
        assert result == {"steps": ["a"]}
        assert fake_run.call_count == 2

    def test_raises_after_exhausting_retries(self, fake_run):
        fake_run.return_value = MagicMock(returncode=0, stdout=_cli_payload("nope"), stderr="")
        with pytest.raises(ClaudeCLIError, match="parseable JSON"):
            llm_cli.request_tool_call(model="m", system="S", messages=[], tool=_TOOL, max_tokens=10)


# ---------------------------------------------------------------------------
# Backend dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_api_backend_does_not_spawn_a_process(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_BACKEND", "api")
        client = MagicMock()
        client.messages.create.return_value = MagicMock(content=[MagicMock(text="hello")])

        with patch("app.services.llm_cli.subprocess.run") as run:
            out = complete_text(client, model="m", system="S", messages=[], max_tokens=10)

        assert out == "hello"
        run.assert_not_called()

    def test_cli_backend_ignores_the_anthropic_client(self, fake_run, cli_backend):
        client = MagicMock()
        out = complete_text(client, model="m", system="S", messages=[], max_tokens=10)

        assert out == "OK"
        client.messages.create.assert_not_called()

    def test_cli_tool_call_returns_a_usable_toolcallresult(self, fake_run, cli_backend):
        fake_run.return_value = MagicMock(
            returncode=0, stdout=_cli_payload('{"steps": ["a"]}'), stderr=""
        )
        result = request_tool_call(
            MagicMock(), model="m", system="S", messages=[], tool=_TOOL, max_tokens=10
        )

        assert result.input == {"steps": ["a"]}
        assert result.tool_use_id  # the regeneration loop echoes this back
        # raw_content must round-trip through _flatten_messages for the retry turn.
        assert "steps" in llm_cli._flatten_messages(
            [{"role": "assistant", "content": result.raw_content}]
        )


# ---------------------------------------------------------------------------
# Production guard
# ---------------------------------------------------------------------------


def test_production_refuses_to_boot_on_the_cli_backend(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "LLM_BACKEND", "cli")

    problems = settings.production_secret_problems()

    assert any("LLM_BACKEND" in p for p in problems)
