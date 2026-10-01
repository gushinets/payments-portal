import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";

import { EmailVerificationClient } from "@/features/email-verification";
import { LANGUAGE_TAG_BY_ROUTE_LOCALE } from "@/generated/locales";
import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createLocalizedMetadata } from "@/i18n/metadata";

export async function generateMetadata(): Promise<Metadata> {
  return createLocalizedMetadata(await getCurrentRouteLocale(), "/verify-email");
}

export default async function VerifyEmailPage() {
  const [messages, locale] = await Promise.all([
    getMessages(),
    getCurrentRouteLocale()
  ]);

  return (
    <NextIntlClientProvider
      messages={{
        Auth: messages.Auth,
        EmailVerification: messages.EmailVerification
      }}
    >
      <EmailVerificationClient
        languageTag={LANGUAGE_TAG_BY_ROUTE_LOCALE[locale]}
      />
    </NextIntlClientProvider>
  );
}
