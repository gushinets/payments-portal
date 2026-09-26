import type { Metadata } from "next";

import { AccountClient } from "@/features/account";
import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createLocalizedMetadata } from "@/i18n/metadata";

export async function generateMetadata(): Promise<Metadata> {
  return createLocalizedMetadata(await getCurrentRouteLocale(), "/account");
}

export default function AccountPage() {
  return <AccountClient />;
}
