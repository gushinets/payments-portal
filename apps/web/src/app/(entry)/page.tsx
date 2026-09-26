import { redirect } from "next/navigation";

import { DEFAULT_ROUTE_LOCALE } from "@/generated/locales";

export default function RootEntryPage() {
  redirect(`/${DEFAULT_ROUTE_LOCALE}`);
}
