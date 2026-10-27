// Live review/preparation/Widget reads share the API's bounded preflight policy
// (up to 120 seconds). Allow response/DB overhead beyond that server deadline.
// Local status and identity requests retain the ordinary transport timeout.
export const billingRequestTimeoutMs = 130_000;
