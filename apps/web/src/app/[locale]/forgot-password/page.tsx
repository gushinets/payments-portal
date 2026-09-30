import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";

import { PasswordResetRequestClient } from "@/features/password-reset";
import { LANGUAGE_TAG_BY_ROUTE_LOCALE } from "@/generated/locales";
import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createLocalizedMetadata } from "@/i18n/metadata";

export async function generateMetadata(): Promise<Metadata> {
  return createLocalizedMetadata(
    await getCurrentRouteLocale(),
    "/forgot-password"
  );
}

export default async function ForgotPasswordPage() {
  const routeLocale = await getCurrentRouteLocale();
  const messages = await getMessages();
  const languageTag = LANGUAGE_TAG_BY_ROUTE_LOCALE[routeLocale];

  return (
    <NextIntlClientProvider
      messages={{ PasswordReset: messages.PasswordReset }}
    >
      <PasswordResetRequestClient languageTag={languageTag} />
    </NextIntlClientProvider>
  );
}
