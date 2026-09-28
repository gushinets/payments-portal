import { Suspense } from "react";
import type { RouteLocale } from "@/generated/locales";
import { Link } from "@/i18n/navigation";
import { CookieBanner } from "./CookieBanner";
import { Footer, FooterContent } from "./Footer";
import { HeaderAccount } from "./HeaderAccount";
import { LocaleSwitcher } from "./LocaleSwitcher";

export function SiteShell({
  children,
  footer,
  locale
}: {
  children: React.ReactNode;
  footer: FooterContent;
  locale: RouteLocale;
}) {
  return (
    <div className="site-shell">
      <header className="top-nav">
        <div className="nav-inner">
          <Link className="logo" href="/" aria-label="AnytoolAI">
            Anytool<span>AI</span>
          </Link>
          <nav className="nav-links" aria-label="Основная навигация">
            <Link className="nav-link" href="/products">
              Продукты
            </Link>
            <Suspense fallback={null}>
              <LocaleSwitcher locale={locale} />
            </Suspense>
            <HeaderAccount />
          </nav>
        </div>
      </header>
      <main className="site-main">{children}</main>
      <Footer {...footer} />
      <CookieBanner />
    </div>
  );
}
