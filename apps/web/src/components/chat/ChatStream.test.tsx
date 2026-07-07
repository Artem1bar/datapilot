import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatStream } from "./ChatStream";
import type { ChatMessageV2, CleaningPlanPayload } from "@/types";

function planMessage(datasetId = "ds-A"): ChatMessageV2 {
  const card: CleaningPlanPayload = {
    type: "cleaning_plan",
    summary: "Test plan",
    datasetId,
    steps: [
      {
        operation: "strip_whitespace",
        column: "name",
        params: {},
        description: "Step 1: strip",
        confidence: 0.9,
      },
    ],
  };
  return {
    id: "m1",
    role: "assistant",
    content: "",
    card,
    timestamp: "2020-01-01T00:00:00Z",
  };
}

describe("ChatStream — card actions carry the owning session", () => {
  it("apply carries the session the card was rendered under, regardless of the active session", async () => {
    const user = userEvent.setup();
    const onCardAction = vi.fn();

    // The card belongs to session-A. Even if the app's active session later
    // becomes session-B, this card's Apply must still target session-A.
    render(
      <ChatStream
        sessionId="session-A"
        messages={[planMessage()]}
        onChipClick={() => {}}
        onCardAction={onCardAction}
      />,
    );

    await user.click(screen.getByRole("button", { name: /^Apply 1 step$/ }));

    expect(onCardAction).toHaveBeenCalledTimes(1);
    const [action, , sessionId] = onCardAction.mock.calls[0];
    expect(action).toBe("apply_cleaning");
    expect(sessionId).toBe("session-A");
  });
});
