import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getMessages, getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { PasswordResetConfirmClient } from "@/features/password-reset";
import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createLocalizedMetadata } from "@/i18n/metadata";

export async function generateMetadata(): Promise<Metadata> {
  return createLocalizedMetadata(
    await getCurrentRouteLocale(),
    "/reset-password"
  );
}

export default async function ResetPasswordPage() {
  const [messages, t] = await Promise.all([
    getMessages(),
    getTranslations("PasswordReset")
  ]);

  return (
    <NextIntlClientProvider
      messages={{ PasswordReset: messages.PasswordReset }}
    >
      <Suspense
        fallback={<ResetPasswordFallback message={t("confirm.loading")} />}
      >
        <PasswordResetConfirmClient />
      </Suspense>
    </NextIntlClientProvider>
  );
}

function ResetPasswordFallback({ message }: { message: string }) {
  return (
    <section className="page-section compact auth-page-section">
      <div className="form-panel auth-page-panel">{message}</div>
    </section>
  );
}
