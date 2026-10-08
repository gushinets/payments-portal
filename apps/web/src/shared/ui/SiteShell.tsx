import { Suspense } from "react";
import { NextIntlClientProvider } from "next-intl";
import { getMessages, getTranslations } from "next-intl/server";
import {
  LANGUAGE_TAG_BY_ROUTE_LOCALE,
  type RouteLocale
} from "@/generated/locales";
import { Link } from "@/i18n/navigation";
import { CookieBanner } from "./CookieBanner";
import { Footer, FooterContent } from "./Footer";
import { HeaderAccount } from "./HeaderAccount";
import { HeaderNavigation } from "./HeaderNavigation";
import { LocaleSwitcher } from "./LocaleSwitcher";

export async function SiteShell({
  children,
  footer,
  locale
}: {
  children: React.ReactNode;
  footer: FooterContent;
  locale: RouteLocale;
}) {
  const [messages, t] = await Promise.all([
    getMessages(),
    getTranslations("Navigation")
  ]);

  return (
    <div className="site-shell">
      <NextIntlClientProvider
        messages={{
          Navigation: messages.Navigation,
          Auth: messages.Auth,
          EmailVerification: messages.EmailVerification
        }}
      >
        <header className="top-nav">
          <nav className="nav-inner" aria-label={t("mainAriaLabel")}>
            <Link className="logo" href="/" aria-label="AnyToolAI">
              AnyTool<span>AI</span>
            </Link>
            <HeaderNavigation />
            <div className="nav-actions">
              <Suspense fallback={null}>
                <LocaleSwitcher locale={locale} />
              </Suspense>
              <HeaderAccount
                languageTag={LANGUAGE_TAG_BY_ROUTE_LOCALE[locale]}
              />
            </div>
          </nav>
        </header>
      </NextIntlClientProvider>
      <main className="site-main">{children}</main>
      <Footer {...footer} />
      <NextIntlClientProvider
        messages={{ CookieBanner: messages.CookieBanner }}
      >
        <CookieBanner />
      </NextIntlClientProvider>
    </div>
  );
}
