import { describe, it, expect } from "vitest";
import { detectIntent, intentRequiresData, type ChatIntent } from "./intent";

describe("detectIntent", () => {
  it("classifies cleaning requests", () => {
    expect(detectIntent("clean my dataset")).toBe("clean");
    expect(detectIntent("Please CLEAN this file")).toBe("clean");
    expect(detectIntent("can you clean up the columns?")).toBe("clean");
  });

  describe("manipulation verbs", () => {
    const verbs = [
      "delete the empty rows",
      "remove duplicates",
      "drop the id column",
      "rename price to amount",
      "sort by date",
      "filter to 2024 only",
      "add column total",
      "merge first and last name",
      "format the phone numbers",
      "move column name to the front",
      "split the address field",
      "reorder the columns",
      "restructure the sheet",
    ];
    it.each(verbs)("classifies %j as manipulate", (text) => {
      expect(detectIntent(text)).toBe("manipulate");
    });

    it("requires whole words (no substring false positives)", () => {
      // "drop" is a manipulation verb; "dropdown" must not trip it.
      expect(detectIntent("open the dropdown menu")).toBe("chat");
      expect(detectIntent("format")).toBe("manipulate");
    });
  });

  it("classifies analysis requests (both spellings)", () => {
    expect(detectIntent("analyze the revenue")).toBe("analyze");
    expect(detectIntent("analyse spending trends")).toBe("analyze");
    expect(detectIntent("ANALYZE my data")).toBe("analyze");
  });

  it("classifies report requests", () => {
    expect(detectIntent("create a report")).toBe("report");
    expect(detectIntent("generate a summary REPORT")).toBe("report");
  });

  it("falls back to chat for anything else", () => {
    expect(detectIntent("hello")).toBe("chat");
    expect(detectIntent("what can you do?")).toBe("chat");
    expect(detectIntent("")).toBe("chat");
  });

  describe("precedence when multiple intents match", () => {
    it("clean beats manipulate, analyze, and report", () => {
      expect(detectIntent("clean and delete the bad rows")).toBe("clean");
      expect(detectIntent("clean then analyze")).toBe("clean");
    });

    it("manipulate beats analyze and report", () => {
      expect(detectIntent("delete rows then analyze")).toBe("manipulate");
      expect(detectIntent("filter and report")).toBe("manipulate");
    });

    it("analyze beats report", () => {
      expect(detectIntent("analyze and report the results")).toBe("analyze");
    });
  });
});

describe("intentRequiresData", () => {
  it("is true for every data-oriented intent", () => {
    const dataIntents: ChatIntent[] = ["clean", "manipulate", "analyze", "report"];
    for (const intent of dataIntents) {
      expect(intentRequiresData(intent)).toBe(true);
    }
  });

  it("is false only for free-form chat", () => {
    expect(intentRequiresData("chat")).toBe(false);
  });
});
