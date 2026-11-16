import type { BackendCodeRequest, BackendCodeResponse } from "@/generated/api-contracts/types.gen";
import { postJson } from "./transport";

export function createBackendSessionCode(token: string, consumerId: string, challenge: string): Promise<BackendCodeResponse> {
  const request: BackendCodeRequest = { consumer_id: consumerId, code_challenge: challenge, code_challenge_method: "S256" };
  return postJson<BackendCodeResponse>("/api/backend-session-codes", request, "BackendCodeResponse", token);
}
