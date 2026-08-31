import { FileText, WandSparkles } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type ProductCode = "document-summary" | "prompt-optimizer";

export type Product = {
  code: ProductCode;
  name: string;
  type: string;
  tagline: string;
  description: string;
  valuePoints: string[];
  freeLimit: string;
  plan: {
    code: string;
    name: string;
    priceRub: number;
    period: "month";
    trialDays: number;
    paymentDescription: string;
  };
  Icon: LucideIcon;
};

/**
 * Compatibility snapshot for checkout, account, and payment-result surfaces
 * that are intentionally migrated by later ANY-370 steps.
 */
export const products: Product[] = [
  {
    code: "document-summary",
    name: "Document Summary",
    type: "Chrome extension",
    tagline: "Мгновенное краткое содержание любого документа",
    description:
      "Расширение помогает быстро получать summary документов и веб-страниц без лишних ручных действий.",
    valuePoints: [
      "Три режима: полное summary, короткое summary и тезисы",
      "Работает с PDF, TXT и веб-страницами",
      "Определяет язык документа и отвечает на нём же",
      "Позволяет экспортировать результат в PDF",
      "Файлы не сохраняются на серверах"
    ],
    freeLimit: "3 summary в месяц",
    plan: {
      code: "document-summary-pro",
      name: "Document Summary Pro",
      priceRub: 990,
      period: "month",
      trialDays: 7,
      paymentDescription: "Подписка Document Summary Pro на 1 месяц"
    },
    Icon: FileText
  },
  {
    code: "prompt-optimizer",
    name: "Prompt Optimizer",
    type: "Chrome extension",
    tagline: "Улучшение промптов для ИИ в один клик",
    description:
      "Расширение улучшает промпты прямо в привычном интерфейсе и показывает, что именно стало лучше.",
    valuePoints: [
      "Работает поверх ChatGPT, Claude, Perplexity, Groq и DeepSeek",
      "Показывает, что именно улучшено в промпте",
      "Возвращает улучшенный промпт обратно в чат одним кликом",
      "Сохраняет готовые промпты в библиотеке"
    ],
    freeLimit: "50 оптимизаций в месяц",
    plan: {
      code: "prompt-optimizer-pro",
      name: "Prompt Optimizer Pro",
      priceRub: 990,
      period: "month",
      trialDays: 7,
      paymentDescription: "Подписка Prompt Optimizer Pro на 1 месяц"
    },
    Icon: WandSparkles
  }
];

export function findProduct(
  code: string | null | undefined
): Product | undefined {
  if (!code) {
    return undefined;
  }

  return products.find((product) => product.code === code);
}
