import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";

import {
  paymentMethods,
  seller,
  supportEmail
} from "@/features/catalog";
import { legalLinks } from "@/features/legal";
import {
  LANGUAGE_TAG_BY_ROUTE_LOCALE,
  SUPPORTED_ROUTE_LOCALES,
  isRouteLocale
} from "@/generated/locales";
import { APP_METADATA_BASE } from "@/i18n/metadata";
import { SiteShell } from "@/shared/ui";

import "../account.css";
import "../catalog.css";
import "../globals.css";
import "../legal-and-footer.css";
import "../responsive.css";

type LocaleLayoutProps = Readonly<{
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}>;

export const metadata: Metadata = {
  metadataBase: APP_METADATA_BASE,
  title: "AnytoolAI - RU",
  description: "RU-версия платформы цифровых сервисов AnytoolAI."
};

export const dynamicParams = false;

export function generateStaticParams() {
  return SUPPORTED_ROUTE_LOCALES.map((locale) => ({ locale }));
}

export default async function LocaleLayout({
  children,
  params
}: LocaleLayoutProps) {
  const { locale } = await params;

  if (!isRouteLocale(locale)) {
    notFound();
  }

  const messages = await getMessages();

  return (
    <html lang={LANGUAGE_TAG_BY_ROUTE_LOCALE[locale]}>
      <body>
        <NextIntlClientProvider locale={locale} messages={messages}>
          <SiteShell
            footer={{ seller, supportEmail, legalLinks, paymentMethods }}
          >
            {children}
          </SiteShell>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
