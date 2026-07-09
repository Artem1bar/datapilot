/**
 * Zero-dependency stub of the Anthropic Messages API for E2E runs.
 *
 * The backend reaches it via ANTHROPIC_BASE_URL (the SDK reads that env var
 * directly). Every AI call in the golden path is a forced tool call
 * (structured outputs), so the stub answers POST /v1/messages by inspecting
 * which tool the request forces and returning a canned tool_use block.
 * Unknown tools get a 500 so a spec fails loudly instead of hanging.
 */

import http from "node:http";

const PORT = Number(process.env.STUB_PORT || 9797);

// Canned plan for e2e/fixtures/messy_people.csv: one whitespace fix + dedup.
// Deterministic verification passes for both, so no verification-agent call
// is ever made — the plan call is the only AI dependency in the golden path.
const CLEANING_PLAN = {
  summary: "Stubbed 2-step cleaning plan",
  steps: [
    {
      operation: "strip_whitespace",
      column: "name",
      params: {},
      description: "Step 1: Strip leading/trailing whitespace from name.",
      rationale: "Values like ' alice ' carry stray whitespace.",
      confidence: 0.95,
    },
    {
      operation: "deduplicate",
      column: null,
      params: {},
      description: "Step 2: Remove duplicate rows.",
      rationale: "Rows 2/3 are exact duplicates.",
      confidence: 0.9,
    },
  ],
};

function toolUseResponse(toolName, input) {
  return {
    id: "msg_stub_" + Math.random().toString(36).slice(2, 10),
    type: "message",
    role: "assistant",
    model: "claude-e2e-stub",
    content: [
      {
        type: "tool_use",
        id: "toolu_stub_" + Math.random().toString(36).slice(2, 10),
        name: toolName,
        input,
      },
    ],
    stop_reason: "tool_use",
    stop_sequence: null,
    usage: { input_tokens: 25, output_tokens: 25 },
  };
}

const server = http.createServer((req, res) => {
  if (req.method !== "POST" || !req.url.includes("/messages")) {
    res.writeHead(404).end();
    return;
  }
  let body = "";
  req.on("data", (chunk) => (body += chunk));
  req.on("end", () => {
    let payload;
    try {
      payload = JSON.parse(body);
    } catch {
      res.writeHead(400).end();
      return;
    }
    const toolNames = (payload.tools || []).map((t) => t.name);
    console.log(`[stub-anthropic] ${payload.model} tools=${toolNames.join(",") || "none"}`);

    if (toolNames.includes("submit_cleaning_plan")) {
      res
        .writeHead(200, { "content-type": "application/json" })
        .end(JSON.stringify(toolUseResponse("submit_cleaning_plan", CLEANING_PLAN)));
      return;
    }

    // Anything else is unexpected in the golden path — fail loudly.
    console.error(`[stub-anthropic] UNEXPECTED tool request: ${toolNames.join(",")}`);
    res
      .writeHead(500, { "content-type": "application/json" })
      .end(JSON.stringify({ error: { message: `stub has no answer for tools: ${toolNames}` } }));
  });
});

server.listen(PORT, () => console.log(`[stub-anthropic] listening on :${PORT}`));
