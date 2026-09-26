import { getRequestConfig } from "next-intl/server";

import { type RouteLocale } from "@/generated/locales";

import { getCurrentRouteLocale } from "./current-locale";

const messageLoaders: Record<
  RouteLocale,
  () => Promise<Record<string, never>>
> = {
  en: async () => (await import("../messages/en.json")).default,
  fr: async () => (await import("../messages/fr.json")).default,
  it: async () => (await import("../messages/it.json")).default,
  de: async () => (await import("../messages/de.json")).default,
  es: async () => (await import("../messages/es.json")).default,
  ru: async () => (await import("../messages/ru.json")).default,
  pt: async () => (await import("../messages/pt.json")).default
};

export default getRequestConfig(async () => {
  const routeLocale = await getCurrentRouteLocale();

  return {
    locale: routeLocale,
    messages: await messageLoaders[routeLocale]()
  };
});
