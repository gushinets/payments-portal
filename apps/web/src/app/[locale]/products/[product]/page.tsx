import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ProductDetail, productPresentation } from "@/features/catalog";
import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createLocalizedMetadata } from "@/i18n/metadata";

type ProductPageProps = Readonly<{
  params: Promise<{ locale: string; product: string }>;
}>;

function getProduct(slug: string) {
  const product = productPresentation.find((item) => item.slug === slug);

  if (!product) {
    notFound();
  }

  return product;
}

export const dynamicParams = false;

export function generateStaticParams() {
  return productPresentation.map(({ slug }) => ({ product: slug }));
}

export async function generateMetadata({
  params
}: ProductPageProps): Promise<Metadata> {
  const [{ product: productSlug }, routeLocale] = await Promise.all([
    params,
    getCurrentRouteLocale()
  ]);
  const product = getProduct(productSlug);

  return createLocalizedMetadata(
    routeLocale,
    `/products/${product.slug}`
  );
}

export default async function ProductDetailPage({
  params
}: ProductPageProps) {
  const { product: productSlug } = await params;
  const product = getProduct(productSlug);

  return <ProductDetail product={product} />;
}
