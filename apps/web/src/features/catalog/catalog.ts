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

export type ProductPresentation = {
  code: "document-summary" | "prompt-optimizer";
  messageKey: "documentSummary" | "promptOptimizer";
  messageValues: Record<string, string | number>;
  Icon: typeof FileText;
};

export const productPresentation: readonly ProductPresentation[] = [
  {
    code: "document-summary",
    messageKey: "documentSummary",
    messageValues: {
      freeLimitAmount: 3,
      summaryModeCount: 3,
      supportedFormats: "PDF, TXT",
      exportFormat: "PDF"
    },
    Icon: FileText
  },
  {
    code: "prompt-optimizer",
    messageKey: "promptOptimizer",
    messageValues: {
      freeLimitAmount: 50,
      supportedServices: "ChatGPT, Claude, Perplexity, Groq, DeepSeek"
    },
    Icon: WandSparkles
  }
];

export const catalogRegion = "RU";
export const accountCount = 1;
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
