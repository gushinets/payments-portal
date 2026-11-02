// Localize the integer and decimal separator without converting money to Number.
// The API supplies fixed-point major units padded to the proven account scale.
export function formatCatalogMoney(amount: string, currency: string, intlLocale: string): string {
  const [whole, fraction] = amount.split(".");
  const integer = new Intl.NumberFormat(intlLocale, { maximumFractionDigits: 0 })
    .format(BigInt(whole));
  const separator = new Intl.NumberFormat(intlLocale).formatToParts(1.1)
    .find((part) => part.type === "decimal")?.value ?? ".";
  return `${integer}${fraction === undefined ? "" : separator + fraction}\u00a0${currency}`;
}
