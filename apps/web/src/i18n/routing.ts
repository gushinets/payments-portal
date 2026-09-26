import { defineRouting } from "next-intl/routing";

import {
  DEFAULT_ROUTE_LOCALE,
  SUPPORTED_ROUTE_LOCALES,
} from "@/generated/locales";

export const routing = defineRouting({
  locales: SUPPORTED_ROUTE_LOCALES,
  defaultLocale: DEFAULT_ROUTE_LOCALE,
  localePrefix: "always",
  localeDetection: false,
  localeCookie: false,
  alternateLinks: false,
});
