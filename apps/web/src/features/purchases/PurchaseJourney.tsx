import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";

import { PurchaseJourneyClient } from "./PurchaseJourneyClient";

export async function PurchaseJourney({ productId }: { productId: string }) {
  const messages = await getMessages();
  return (
    <NextIntlClientProvider
      messages={{
        Purchase: messages.Purchase,
        CatalogPreview: messages.CatalogPreview
      }}
    >
      <PurchaseJourneyClient key={productId} productId={productId} />
    </NextIntlClientProvider>
  );
}
