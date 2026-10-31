import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest import mock

from claude_counter import statusline as sl

SID = "11111111-2222-3333-4444-555555555555"


class IsolatedTestCase(unittest.TestCase):
    """Points every file the script reads or writes into a temporary folder."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.transcripts = os.path.join(self.dir, "projects")
        os.makedirs(self.transcripts)
        for name, value in {
            "COST_STATE_FILE": os.path.join(self.dir, "state.json"),
            "PRICING_CACHE_FILE": os.path.join(self.dir, "pricing.json"),
            "PRICING_REFRESH_STAMP_FILE": os.path.join(self.dir, "refresh"),
            "CLAUDE_SETTINGS_FILE": os.path.join(self.dir, "settings.json"),
            "TRANSCRIPT_DIR": self.transcripts,
            "API_PRICING": dict(sl.FALLBACK_PRICING),
        }.items():
            patcher = mock.patch.object(sl, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        popen = mock.patch.object(sl.subprocess, "Popen")
        popen.start()
        self.addCleanup(popen.stop)
        env = mock.patch.dict(os.environ, {"COLUMNS": "1000"})
        env.start()
        self.addCleanup(env.stop)

    def write_state(self, **fields):
        state = {"billing_period": sl._billing_period_key(), **fields}
        with open(sl.COST_STATE_FILE, "w") as f:
            json.dump(state, f)

    def read_state(self):
        with open(sl.COST_STATE_FILE) as f:
            return json.load(f)

    def write_transcript(self, path, entries):
        path = os.path.join(self.transcripts, path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.writelines(json.dumps(e) + "\n" for e in entries)

    def render(self, payload, *args):
        argv = ["claude-counter", "--no-git", "--no-powerline", *args]
        out = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
                redirect_stdout(out):
            sl.main()
        return out.getvalue()


def payload(**extra):
    data = {
        "session_id": SID,
        "cwd": "/tmp/app",
        "model": {"display_name": "Opus 5.5"},
        "context_window": {
            "total_input_tokens": 300_000,
            "total_output_tokens": 500,
            "context_window_size": 1_000_000,
            "used_percentage": 30,
            "current_usage": {"cache_read_input_tokens": 299_000, "cache_creation_input_tokens": 900},
        },
    }
    data.update(extra)
    return data


class LiveRenderTests(IsolatedTestCase):
    def test_session_cost_is_claude_codes_total_cost(self):
        self.write_state()
        out = self.render(payload(cost={"total_cost_usd": 12.34}))
        self.assertIn(f"{sl.COST_ICON}12.34", out)
        self.assertEqual(self.read_state()["billing_sessions"], {SID: 12.34})

    def test_month_total_adds_other_sessions(self):
        self.write_state(billing_sessions={"older": 100.0})
        out = self.render(payload(cost={"total_cost_usd": 12.34}))
        self.assertIn(f"{sl.COST_ICON}112.34/mo", out)

    def test_missing_total_cost_keeps_stored_cost(self):
        self.write_state(billing_sessions={SID: 7.5})
        out = self.render(payload())
        self.assertEqual(self.read_state()["billing_sessions"], {SID: 7.5})
        self.assertIn(f"{sl.COST_ICON}7.50/mo", out)

    def test_render_keeps_synced_water_and_shows_it_once(self):
        self.write_state(billing_water={SID: 2.0})
        out = self.render(payload(cost={"total_cost_usd": 1.0}))
        self.assertEqual(self.read_state()["billing_water"], {SID: 2.0})
        self.assertEqual(out.count(sl.WATER_ICON), 1)
        self.assertIn(f"{sl.WATER_ICON}2.0L/mo", out)

    def test_no_cost_still_shows_month_water(self):
        self.write_state(billing_sessions={SID: 3.0}, billing_water={SID: 2.0})
        out = self.render(payload(cost={"total_cost_usd": 9.0}), "--no-cost")
        self.assertIn(f"{sl.WATER_ICON}2.0L/mo", out)
        self.assertNotIn(sl.COST_ICON, out)
        self.assertEqual(self.read_state()["billing_sessions"], {SID: 3.0})


def assistant(request_id, model, usage, session_id=SID):
    return {
        "type": "assistant",
        "requestId": request_id,
        "sessionId": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "message": {"model": model, "usage": usage},
    }


class SyncTests(IsolatedTestCase):
    def test_keeps_last_streaming_update_per_request(self):
        final = {"input_tokens": 10, "output_tokens": 100}
        self.write_transcript(f"proj/{SID}.jsonl", [
            assistant("req1", "claude-opus-5-5", {"input_tokens": 10, "output_tokens": 1}),
            assistant("req1", "claude-opus-5-5", final),
        ])
        sl.sync_historical_costs()
        self.assertAlmostEqual(
            self.read_state()["billing_sessions"][SID],
            sl._estimate_cost_from_usage(final, "claude-opus-5-5"),
        )

    def test_prices_cache_by_model_rate_and_write_duration(self):
        usage = {
            "input_tokens": 1_000,
            "output_tokens": 2_000,
            "cache_read_input_tokens": 1_000_000,
            "cache_creation_input_tokens": 30_000,
            "cache_creation": {"ephemeral_5m_input_tokens": 10_000, "ephemeral_1h_input_tokens": 20_000},
        }
        # Opus 5.5: $4 input, $20 output, $0.20 cache read, $5 5m write, $8 1h write
        expected = (1_000 * 4 + 2_000 * 20 + 1_000_000 * 0.2 + 10_000 * 5 + 20_000 * 8) / 1e6
        self.assertAlmostEqual(sl._estimate_cost_from_usage(usage, "claude-opus-5-5"), expected)

    def test_cache_writes_without_split_count_as_one_hour(self):
        usage = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 1_000_000}
        self.assertAlmostEqual(sl._estimate_cost_from_usage(usage, "claude-fable-5-1"), 20.0)

    def test_adds_advisor_tokens_at_the_advisors_model(self):
        # Top-level usage sums only the "message" iterations.
        usage = {
            "input_tokens": 0,
            "output_tokens": 1_000,
            "iterations": [
                {"type": "message", "input_tokens": 0, "output_tokens": 1_000},
                {"type": "advisor_message", "model": "claude-fable-5-1", "input_tokens": 100_000, "output_tokens": 2_000},
            ],
        }
        # Opus output $20, Fable input $10 and output $50
        expected = (1_000 * 20 + 100_000 * 10 + 2_000 * 50) / 1e6
        self.assertAlmostEqual(sl._estimate_cost_from_usage(usage, "claude-opus-5-5"), expected)
        self.assertGreater(
            sl._estimate_water_from_usage(usage, "claude-opus-5-5"),
            sl._estimate_water_from_usage({"output_tokens": 1_000}, "claude-opus-5-5"),
        )

    def test_includes_subagent_transcripts(self):
        main_usage = {"input_tokens": 1_000, "output_tokens": 100}
        agent_usage = {"input_tokens": 2_000, "output_tokens": 300}
        self.write_transcript(f"proj/{SID}.jsonl", [assistant("req1", "claude-opus-5-5", main_usage)])
        self.write_transcript(f"proj/{SID}/subagents/agent-a1.jsonl", [assistant("req2", "claude-fable-5-1", agent_usage)])
        sl.sync_historical_costs()
        self.assertAlmostEqual(
            self.read_state()["billing_sessions"][SID],
            sl._estimate_cost_from_usage(main_usage, "claude-opus-5-5")
            + sl._estimate_cost_from_usage(agent_usage, "claude-fable-5-1"),
        )


def cost_state(total, model_usage, session_id=SID):
    return {"type": "cost-state", "sessionId": session_id, "totalCostUSD": total, "modelUsage": model_usage}


class SyncCostStateTests(IsolatedTestCase):
    def test_uses_claude_codes_session_total_over_token_pricing(self):
        model_usage = {"claude-opus-5-5": {
            "inputTokens": 1_000, "outputTokens": 2_000,
            "cacheReadInputTokens": 100_000, "cacheCreationInputTokens": 5_000, "costUSD": 9.5,
        }}
        self.write_transcript(f"proj/{SID}.jsonl", [
            assistant("req1", "claude-opus-5-5", {"input_tokens": 10, "output_tokens": 100}),
            cost_state(4.0, {}),
            cost_state(9.5, model_usage),
        ])
        self.write_transcript(f"proj/{SID}/subagents/agent-a1.jsonl", [
            assistant("req2", "claude-opus-5-5", {"input_tokens": 10, "output_tokens": 100}),
        ])
        sl.sync_historical_costs()
        state = self.read_state()
        self.assertEqual(state["billing_sessions"], {SID: 9.5})
        self.assertAlmostEqual(state["billing_water"][SID], sl._estimate_water_from_usage({
            "input_tokens": 1_000, "output_tokens": 2_000,
            "cache_read_input_tokens": 100_000, "cache_creation_input_tokens": 5_000,
        }, "claude-opus-5-5"))

    def test_continued_session_counts_once(self):
        child = "99999999-8888-7777-6666-555555555555"
        self.write_transcript(f"proj/{SID}.jsonl", [
            assistant("req1", "claude-fable-5-1", {"input_tokens": 1_000, "output_tokens": 100}),
            cost_state(5.0, {}),
            {"type": "continued-in", "sessionId": SID, "continuedInSessionId": child},
        ])
        # The continuation copies the parent's requests, and its total includes the parent's cost.
        self.write_transcript(f"proj/{child}.jsonl", [
            assistant("req1", "claude-fable-5-1", {"input_tokens": 1_000, "output_tokens": 100}, session_id=child),
            assistant("req2", "claude-fable-5-1", {"input_tokens": 1_000, "output_tokens": 100}, session_id=child),
            cost_state(6.0, {}, session_id=child),
        ])
        sl.sync_historical_costs()
        self.assertEqual(self.read_state()["billing_sessions"], {child: 6.0})


class PricingTests(IsolatedTestCase):
    def test_fetch_stores_litellm_cache_rates(self):
        litellm = {
            "claude-haiku-5-5": {
                "input_cost_per_token": 1e-07,
                "output_cost_per_token": 5e-07,
                "cache_read_input_token_cost": 1e-08,
                "cache_creation_input_token_cost": 1.25e-07,
                "cache_creation_input_token_cost_above_1hr": 2e-07,
            },
        }
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(litellm).encode()
        with mock.patch.object(sl.urllib.request, "urlopen", return_value=response):
            self.assertTrue(sl.fetch_and_update_pricing(force=True))
        with open(sl.PRICING_CACHE_FILE) as f:
            self.assertEqual(json.load(f)["pricing"]["haiku"], [0.1, 0.5, 0.01, 0.125, 0.2])
        self.assertEqual(sl.API_PRICING["haiku"], (0.1, 0.5, 0.01, 0.125, 0.2))

    def test_load_ignores_entries_without_cache_rates(self):
        with open(sl.PRICING_CACHE_FILE, "w") as f:
            json.dump({"pricing": {"opus": [9.0, 9.0]}}, f)
        self.assertEqual(sl._load_pricing()["opus"], sl.FALLBACK_PRICING["opus"])


if __name__ == "__main__":
    unittest.main()
