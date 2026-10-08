"use client";

import { useTranslations } from "next-intl";

import { Link, usePathname } from "@/i18n/navigation";

const navigationItems = [
  { href: "/products", messageKey: "products" },
  { href: "/pricing", messageKey: "pricing" }
] as const;

export function HeaderNavigation() {
  const t = useTranslations("Navigation");
  const pathname = usePathname();

  return (
    <div className="nav-links">
      {navigationItems.map(({ href, messageKey }) => {
        const isCurrentPage = pathname === href;
        const isCurrentSection = pathname.startsWith(`${href}/`);

        return (
          <Link
            className="nav-link"
            href={href}
            aria-current={
              isCurrentPage ? "page" : isCurrentSection ? "location" : undefined
            }
            key={href}
          >
            {t(messageKey)}
          </Link>
        );
      })}
    </div>
  );
}
