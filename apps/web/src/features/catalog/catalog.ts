import {
  FileText,
  Globe,
  Languages,
  List,
  MessageSquareQuote,
  MousePointer2,
  ShieldCheck,
  Sparkles,
  SquarePen,
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
  PreviewIcon: typeof FileText;
  highlights: readonly {
    messageKey: "focus" | "context" | "approach";
    Icon: typeof FileText;
  }[];
};

export const productPresentation: readonly ProductPresentation[] = [
  {
    slug: "document-summary",
    messageKey: "documentSummary",
    Icon: FileText,
    PreviewIcon: List,
    highlights: [
      { messageKey: "focus", Icon: FileText },
      { messageKey: "context", Icon: Globe },
      { messageKey: "approach", Icon: MousePointer2 }
    ]
  },
  {
    slug: "prompt-optimizer",
    messageKey: "promptOptimizer",
    Icon: WandSparkles,
    PreviewIcon: MessageSquareQuote,
    highlights: [
      { messageKey: "focus", Icon: SquarePen },
      { messageKey: "context", Icon: MousePointer2 },
      { messageKey: "approach", Icon: Sparkles }
    ]
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
