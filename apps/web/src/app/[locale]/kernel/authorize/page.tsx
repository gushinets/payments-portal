import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";
import { AccountClient, KernelAuthorization } from "@/features/account";
import { LANGUAGE_TAG_BY_ROUTE_LOCALE } from "@/generated/locales";
import { getCurrentRouteLocale } from "@/i18n/current-locale";

export default async function KernelAuthorizePage() {
  const [messages, locale] = await Promise.all([getMessages(), getCurrentRouteLocale()]);
  return <NextIntlClientProvider messages={{ Auth: messages.Auth, Account: messages.Account, EmailVerification: messages.EmailVerification, KernelSession: messages.KernelSession }}>
    <AccountClient languageTag={LANGUAGE_TAG_BY_ROUTE_LOCALE[locale]}><KernelAuthorization /></AccountClient>
  </NextIntlClientProvider>;
}
