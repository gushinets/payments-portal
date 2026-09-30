import { render } from "@testing-library/react";
import { NextIntlClientProvider, type AbstractIntlMessages } from "next-intl";
import type { ReactElement } from "react";

import type { RouteLocale } from "@/generated/locales";

export function renderWithIntl(
  ui: ReactElement,
  {
    locale,
    messages
  }: { locale: RouteLocale; messages: AbstractIntlMessages }
) {
  globalThis.__NEXT_INTL_LOCALE__ = locale;

  return render(
    <NextIntlClientProvider locale={locale} messages={messages}>
      {ui}
    </NextIntlClientProvider>
  );
}
