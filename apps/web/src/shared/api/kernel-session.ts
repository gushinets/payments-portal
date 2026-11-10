import type { KernelCodeRequest, KernelCodeResponse } from "@/generated/api-contracts/types.gen";
import { postJson } from "./transport";

export function createKernelSessionCode(token: string, challenge: string): Promise<KernelCodeResponse> {
  const request: KernelCodeRequest = { code_challenge: challenge, code_challenge_method: "S256" };
  return postJson<KernelCodeResponse>("/api/kernel-session-codes", request, "KernelCodeResponse", token);
}
