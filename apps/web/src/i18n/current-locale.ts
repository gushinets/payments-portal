import { locale } from "next/root-params";
import { notFound } from "next/navigation";

import { isRouteLocale, type RouteLocale } from "@/generated/locales";

export async function getCurrentRouteLocale(): Promise<RouteLocale> {
  const routeLocale = await locale();

  if (!isRouteLocale(routeLocale)) {
    notFound();
  }

  return routeLocale;
}
