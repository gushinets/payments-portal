import {
  FileText,
  Languages,
  MessageSquareQuote,
  ShieldCheck,
  Sparkles,
  WandSparkles
} from "lucide-react";

export const supportEmail = "support@any-tool-ai.ru";

export const seller = {
  name: "ИП Говоров Роман Стальевич",
  inn: "143509640374",
  ogrnip: "314547633100101",
  address: "630091 , Новосибирская область, г. Новосибирск"
};

export type PaymentMethod = {
  code: string;
  label: string;
  href?: string;
};

export const paymentMethods: PaymentMethod[] = [];

export type ProductSlug = "document-summary" | "prompt-optimizer";

export type ProductPresentation = {
  slug: ProductSlug;
  messageKey: "documentSummary" | "promptOptimizer";
  Icon: typeof FileText;
};

export const productPresentation: readonly ProductPresentation[] = [
  {
    slug: "document-summary",
    messageKey: "documentSummary",
    Icon: FileText
  },
  {
    slug: "prompt-optimizer",
    messageKey: "promptOptimizer",
    Icon: WandSparkles
  }
];

export const catalogRegion = "RU";
export const legalDocumentLanguage = "RU";

export const platformFacts = [
  {
    messageKey: "catalog",
    Icon: Sparkles
  },
  {
    messageKey: "pricing",
    Icon: ShieldCheck
  },
  {
    messageKey: "account",
    Icon: FileText
  },
  {
    messageKey: "localization",
    Icon: Languages
  }
] as const;

export const platformHighlights = [
  {
    messageKey: "simpleStart",
    Icon: Sparkles
  },
  {
    messageKey: "singleAccount",
    Icon: MessageSquareQuote
  },
  {
    messageKey: "controlledLaunch",
    Icon: ShieldCheck
  }
] as const;
