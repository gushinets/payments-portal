import type { Metadata } from "next";

import { ProductDetail } from "@/features/catalog";
import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createLocalizedMetadata } from "@/i18n/metadata";

type ProductPageProps = Readonly<{
  params: Promise<{ locale: string; product: string }>;
}>;

export async function generateMetadata({
  params
}: ProductPageProps): Promise<Metadata> {
  const [{ product: productSlug }, routeLocale] = await Promise.all([
    params,
    getCurrentRouteLocale()
  ]);
  return createLocalizedMetadata(
    routeLocale,
    `/products/${encodeURIComponent(productSlug)}`
  );
}

export default async function ProductDetailPage({
  params
}: ProductPageProps) {
  const { product: productSlug } = await params;
  return <ProductDetail productId={productSlug} />;
}
