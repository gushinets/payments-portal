import type { Metadata } from "next";
import { createLocalizedMetadata } from "@/i18n/metadata";
import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";
import { AccountClient, BackendAuthorization, parseBackendCallbacks } from "@/features/account";
import { LANGUAGE_TAG_BY_ROUTE_LOCALE } from "@/generated/locales";
import { getCurrentRouteLocale } from "@/i18n/current-locale";

export const dynamic = "force-dynamic";

export async function generateMetadata(): Promise<Metadata> {
  return createLocalizedMetadata(await getCurrentRouteLocale(), "/backend/authorize");
}

export default async function BackendAuthorizePage() {
  const [messages, locale] = await Promise.all([getMessages(), getCurrentRouteLocale()]);
  const callbacks = parseBackendCallbacks(process.env.BACKEND_CALLBACKS);
  return <NextIntlClientProvider messages={{ Auth: messages.Auth, Account: messages.Account, EmailVerification: messages.EmailVerification, BackendSession: messages.BackendSession }}>
    <AccountClient languageTag={LANGUAGE_TAG_BY_ROUTE_LOCALE[locale]} requireVerifiedEmailForChildren><BackendAuthorization callbacks={callbacks} /></AccountClient>
  </NextIntlClientProvider>;
}
