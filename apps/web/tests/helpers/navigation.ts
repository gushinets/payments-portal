export function setRouteSearchParams(params: string | URLSearchParams) {
  globalThis.__NEXT_SEARCH_PARAMS__ =
    typeof params === "string" ? params.replace(/^\?/, "") : params.toString();
}
