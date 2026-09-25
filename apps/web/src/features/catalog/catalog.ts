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
  type: string;
  tagline: string;
  description: string;
  valuePoints: string[];
  freeLimit: string;
  Icon: typeof FileText;
};

export const productPresentation: Record<string, ProductPresentation> = {
  "document-summary": {
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
    Icon: FileText
  },
  "prompt-optimizer": {
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
    Icon: WandSparkles
  }
};

export const platformFacts = [
  {
    label: "Каталог",
    value: "RU",
    detail: "Информация о продуктах AnytoolAI",
    Icon: Sparkles
  },
  {
    label: "Тарифы",
    value: "Скоро",
    detail: "Оформление временно недоступно",
    Icon: ShieldCheck
  },
  {
    label: "Доступ",
    value: "1 аккаунт",
    detail: "Регистрация и вход уже доступны",
    Icon: FileText
  },
  {
    label: "Локализация",
    value: "RU",
    detail: "интерфейс и юридические документы",
    Icon: Languages
  }
];

export const platformHighlights = [
  {
    title: "Простой старт",
    description:
      "Регистрация и юридические документы собраны в одном понятном портале.",
    Icon: Sparkles
  },
  {
    title: "Один аккаунт",
    description:
      "Можно создать аккаунт или войти по email, пока биллинг обновляется.",
    Icon: MessageSquareQuote
  },
  {
    title: "Контролируемый запуск",
    description:
      "Покупки останутся недоступны до подключения новой биллинговой системы.",
    Icon: ShieldCheck
  }
];
