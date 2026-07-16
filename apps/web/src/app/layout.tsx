import type { Metadata } from "next";
import Script from "next/script";
import "./globals.css";
import {
  paymentMethods,
  seller,
  supportEmail
} from "@/features/catalog";
import { legalLinks } from "@/features/legal";
import { SiteShell } from "@/shared/ui";

export const metadata: Metadata = {
  title: "AnytoolAI - RU",
  description: "RU-версия платформы цифровых сервисов AnytoolAI."
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  const cloudPaymentsEnabled =
    process.env.NEXT_PUBLIC_CLOUDPAYMENTS_ENABLED === "true";
  const cloudPaymentsPublicId =
    process.env.NEXT_PUBLIC_CLOUDPAYMENTS_PUBLIC_ID;

  return (
    <html lang="ru">
      <body>
        <SiteShell
          footer={{ seller, supportEmail, legalLinks, paymentMethods }}
        >
          {children}
        </SiteShell>
        {cloudPaymentsEnabled && cloudPaymentsPublicId ? (
          <Script
            src="https://widget.cloudpayments.ru/bundles/cloudpayments"
            strategy="afterInteractive"
          />
        ) : null}
      </body>
    </html>
  );
}
