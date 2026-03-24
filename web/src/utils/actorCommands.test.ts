import { describe, expect, it } from "vitest";

import { buildActorCreateCommand } from "./actorCommands";

describe("buildActorCreateCommand", () => {
  it("uses the full runtime default command when only a model is selected", () => {
    expect(
      buildActorCreateCommand({
        runtime: "codex",
        defaultCommand:
          "codex -c shell_environment_policy.inherit=all --dangerously-bypass-approvals-and-sandbox --search",
        command: "",
        useDefaultCommand: true,
        modelKey: "codex-gpt-5",
      }),
    ).toBe(
      "codex -c shell_environment_policy.inherit=all --dangerously-bypass-approvals-and-sandbox --search --model gpt-5",
    );
  });

  it("appends the selected model to a custom command once", () => {
    expect(
      buildActorCreateCommand({
        runtime: "claude",
        defaultCommand: "claude --dangerously-skip-permissions",
        command: "claude --print",
        useDefaultCommand: false,
        modelKey: "claude-claude-sonnet-4-6",
      }),
    ).toBe("claude --print --model claude-sonnet-4-6");
  });
});
