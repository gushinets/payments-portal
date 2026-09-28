import { getCurrentRouteLocale } from "./current-locale";
import { resolveIntlLocale, type IntlLocale } from "./formatting-locale";

export async function getCurrentIntlLocale(): Promise<IntlLocale> {
  return resolveIntlLocale(await getCurrentRouteLocale());
}
