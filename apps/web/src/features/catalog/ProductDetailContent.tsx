"use client";

import { useState, type ReactNode } from "react";
import { ProductBilling } from "@/features/billing";
import { CatalogPreviewClient } from "./CatalogPreviewClient";

export function ProductDetailContent({ productId, children }: { productId: string; children: ReactNode }) {
  const [offerAvailable, setOfferAvailable] = useState(false);
  return <div className="product-hero">
    <div className="product-hero-content">
      {children}
      <ProductBilling productId={productId} offerAvailable={offerAvailable} />
    </div>
    <CatalogPreviewClient productId={productId} onOfferAvailability={setOfferAvailable} />
  </div>;
}
