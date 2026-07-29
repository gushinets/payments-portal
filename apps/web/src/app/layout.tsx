import type { Metadata } from "next";
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
  return (
    <html lang="ru">
      <body>
        <SiteShell
          footer={{ seller, supportEmail, legalLinks, paymentMethods }}
        >
          {children}
        </SiteShell>
      </body>
    </html>
  );
}
