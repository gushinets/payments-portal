import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";

import { CatalogPreviewClient } from "./CatalogPreviewClient";

export async function CatalogPreview({ productId }: { productId?: string }) {
  const messages = await getMessages();
  return (
    <NextIntlClientProvider messages={{ CatalogPreview: messages.CatalogPreview }}>
      <CatalogPreviewClient productId={productId} />
    </NextIntlClientProvider>
  );
}
