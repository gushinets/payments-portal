import type { Metadata } from "next";

import { PasswordResetRequestClient } from "@/features/password-reset";
import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createLocalizedMetadata } from "@/i18n/metadata";

export async function generateMetadata(): Promise<Metadata> {
  return createLocalizedMetadata(
    await getCurrentRouteLocale(),
    "/forgot-password"
  );
}

export default function ForgotPasswordPage() {
  return <PasswordResetRequestClient />;
}
