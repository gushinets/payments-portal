import Link from "next/link";
import { CookieBanner } from "./CookieBanner";
import { Footer, FooterContent } from "./Footer";
import { HeaderAccount } from "./HeaderAccount";

export function SiteShell({
  children,
  footer
}: {
  children: React.ReactNode;
  footer: FooterContent;
}) {
  return (
    <div className="site-shell">
      <header className="top-nav">
        <div className="nav-inner">
          <Link className="logo" href="/ru" aria-label="AnytoolAI">
            Anytool<span>AI</span>
          </Link>
          <nav className="nav-links" aria-label="Основная навигация">
            <Link className="nav-link" href="/ru/products">
              Продукты
            </Link>
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
