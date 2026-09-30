import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";

import { PasswordResetRequestClient } from "@/features/password-reset";
import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createLocalizedMetadata } from "@/i18n/metadata";

export async function generateMetadata(): Promise<Metadata> {
  return createLocalizedMetadata(
    await getCurrentRouteLocale(),
    "/forgot-password"
  );
}

export default async function ForgotPasswordPage() {
  const messages = await getMessages();

  return (
    <NextIntlClientProvider
      messages={{ PasswordReset: messages.PasswordReset }}
    >
      <PasswordResetRequestClient />
    </NextIntlClientProvider>
  );
}
