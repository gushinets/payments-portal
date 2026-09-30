import { Suspense } from "react";
import { NextIntlClientProvider } from "next-intl";
import { getMessages, getTranslations } from "next-intl/server";
import type { RouteLocale } from "@/generated/locales";
import { Link } from "@/i18n/navigation";
import { CookieBanner } from "./CookieBanner";
import { Footer, FooterContent } from "./Footer";
import { HeaderAccount } from "./HeaderAccount";
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
        messages={{ Navigation: messages.Navigation, Auth: messages.Auth }}
      >
        <header className="top-nav">
          <div className="nav-inner">
            <Link className="logo" href="/" aria-label="AnytoolAI">
              Anytool<span>AI</span>
            </Link>
            <nav className="nav-links" aria-label={t("mainAriaLabel")}>
              <Link className="nav-link" href="/products">
                {t("products")}
              </Link>
              <Suspense fallback={null}>
                <LocaleSwitcher locale={locale} />
              </Suspense>
              <HeaderAccount />
            </nav>
          </div>
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
