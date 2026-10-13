"use client";

import { useCallback, useEffect, useRef } from "react";
import { sessionChangedEvent, sessionStorageKey } from "@/shared/api/auth";

// Shared only by login/register attempts in this tab; never restored on failure.
let currentAuthAttempt: symbol | undefined;

/** Same-tab notifications and native cross-tab changes share one filter. */
export function subscribeToSessionChanges(onChange: () => void): () => void {
  function onStorage(event: StorageEvent) {
    if (
      (event.storageArea === null || event.storageArea === window.localStorage) &&
      (event.key === sessionStorageKey || event.key === null)
    ) {
      onChange();
    }
  }
  window.addEventListener(sessionChangedEvent, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(sessionChangedEvent, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

/** Local lifetime guards with opt-in, same-tab login/register ownership. */
export function useSessionOperation() {
  const scope = useRef({ mounted: false, epoch: 0, version: 0, attempt: 0 });
  useEffect(() => {
    const current = scope.current;
    current.mounted = true;
    current.epoch += 1;
    const unsubscribe = subscribeToSessionChanges(() => {
      current.version += 1;
    });
    return () => {
      current.mounted = false;
      current.epoch += 1;
      unsubscribe();
    };
  }, []);

  const cancel = useCallback(() => {
    scope.current.attempt += 1;
  }, []);
  const begin = useCallback(() => {
    const current = scope.current;
    const epoch = current.epoch;
    const version = current.version;
    const attempt = ++current.attempt;
    const token = window.localStorage.getItem(sessionStorageKey);
    // A stale operation may finish its own spinner, but never a newer attempt.
    const isLatest = () =>
      current.mounted && current.epoch === epoch && current.attempt === attempt;
    return {
      token,
      isLatest,
      isCurrent: () =>
        isLatest() &&
        current.version === version &&
        window.localStorage.getItem(sessionStorageKey) === token
    };
  }, []);
  const beginAuth = useCallback(() => {
    const operation = begin();
    const owner = Symbol();
    currentAuthAttempt = owner;
    return {
      ...operation,
      isCurrent: () => currentAuthAttempt === owner && operation.isCurrent()
    };
  }, [begin]);
  return { begin, beginAuth, cancel };
}
