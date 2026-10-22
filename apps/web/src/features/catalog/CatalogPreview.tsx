import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";

import { CatalogPreviewClient } from "./CatalogPreviewClient";

export async function CatalogPreview({
  productId,
  headingLevel
}: {
  productId?: string;
  headingLevel?: 2 | 3;
}) {
  const messages = await getMessages();
  return (
    <NextIntlClientProvider messages={{ CatalogPreview: messages.CatalogPreview }}>
      <CatalogPreviewClient productId={productId} headingLevel={headingLevel} />
    </NextIntlClientProvider>
  );
}
