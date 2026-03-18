export const BASIC_MCP_CONFIG_SNIPPET = JSON.stringify(
  {
    mcpServers: {
      cccc: { command: "cccc", args: ["mcp"] },
    },
  },
  null,
  2
);

export const OPENCODE_MCP_CONFIG_SNIPPET = JSON.stringify(
  {
    mcp: {
      cccc: {
        type: "local",
        command: ["cccc", "mcp"],
        environment: {},
      },
    },
  },
  null,
  2
);

export const COPILOT_MCP_CONFIG_SNIPPET = JSON.stringify(
  {
    mcpServers: {
      cccc: {
        command: "cccc",
        args: ["mcp"],
        tools: ["*"],
      },
    },
  },
  null,
  2
);
