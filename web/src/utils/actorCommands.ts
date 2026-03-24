import type { SupportedRuntime } from "../types";

type BuildActorCreateCommandArgs = {
  runtime: SupportedRuntime;
  defaultCommand: string;
  command: string;
  useDefaultCommand: boolean;
  modelKey: string;
};

function modelIdFromModelKey(runtime: SupportedRuntime, modelKey: string): string {
  const trimmed = String(modelKey || "").trim();
  if (!trimmed) return "";
  const prefix = `${runtime}-`;
  return trimmed.startsWith(prefix) ? trimmed.slice(prefix.length) : trimmed;
}

export function buildActorCreateCommand({
  runtime,
  defaultCommand,
  command,
  useDefaultCommand,
  modelKey,
}: BuildActorCreateCommandArgs): string {
  const defaultCmd = String(defaultCommand || "").trim();
  const customCmd = String(command || "").trim();
  const modelId = modelIdFromModelKey(runtime, modelKey);

  if (useDefaultCommand) {
    if (!modelId) return "";
    return defaultCmd ? `${defaultCmd} --model ${modelId}` : "";
  }

  if (!customCmd || !modelId || customCmd.includes("--model ")) {
    return customCmd;
  }
  return `${customCmd} --model ${modelId}`;
}
