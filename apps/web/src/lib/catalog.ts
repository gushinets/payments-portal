import {
  BadgeRussianRuble,
  Camera,
  FileCheck2,
  ShieldCheck,
  Sparkles,
  WandSparkles
} from "lucide-react";

export const supportEmail = "info@anytoolai.ru";

export const seller = {
  name: "ИП Говоров Роман Стальевич",
  inn: "143509640374",
  ogrnip: "314547633100101",
  address: "г. Новосибирск, ул. Ленина 1"
};

export const paymentMethods = [
  "Банковская карта",
  "СБП",
  "T-Pay",
  "Мир"
];

export const legalLinks = [
  { href: "/ru/privacy", label: "Политика ПДн" },
  { href: "/ru/offer", label: "Оферта" },
  { href: "/ru/cancellation", label: "Отмена и возврат" },
  { href: "/ru/cookies", label: "Cookies" },
  { href: "/ru/security", label: "Безопасность" }
];

export type ProductCode = "jobact" | "scope-creep-guard";

export type Product = {
  code: ProductCode;
  name: string;
  type: string;
  tagline: string;
  description: string;
  valuePoints: string[];
  plan: {
    code: string;
    name: string;
    priceRub: number;
    period: "month";
    trialDays: number;
    paymentDescription: string;
  };
  Icon: typeof FileCheck2;
};

export const products: Product[] = [
  {
    code: "jobact",
    name: "JobAct",
    type: "Mobile-first сервис",
    tagline: "Цифровой акт выполненных работ",
    description:
      "Список работ, материалы, фото до/после, PDF на подпись и статус оплаты в одном коротком сценарии.",
    valuePoints: [
      "Собирает акт и состав работ",
      "Фиксирует материалы и фото",
      "Готовит PDF для подписи",
      "Помогает контролировать оплату"
    ],
    plan: {
      code: "jobact-start",
      name: "JobAct Start",
      priceRub: 990,
      period: "month",
      trialDays: 7,
      paymentDescription: "Подписка JobAct Start на 1 месяц"
    },
    Icon: Camera
  },
  {
    code: "scope-creep-guard",
    name: "Scope Creep Guard",
    type: "Chrome Extension",
    tagline: "AI-контроль изменения scope",
    description:
      "Сравнение нового запроса с исходным scope и генерация draft Change Order для согласования допработ.",
    valuePoints: [
      "Сравнивает новый запрос и исходный объем",
      "Подсвечивает scope creep",
      "Готовит черновик change order",
      "Снижает риск неоплаченных допработ"
    ],
    plan: {
      code: "scope-guard-start",
      name: "Scope Guard Start",
      priceRub: 1490,
      period: "month",
      trialDays: 7,
      paymentDescription: "Подписка Scope Guard Start на 1 месяц"
    },
    Icon: WandSparkles
  }
];

export const demoPayment = {
  name: "Тестовый платеж",
  amountRub: 1,
  purpose: "тестовая проверка платежного сценария"
};

export const platformFacts = [
  {
    label: "Продукта",
    value: "2",
    detail: "JobAct и Scope Guard",
    Icon: Sparkles
  },
  {
    label: "Пробный период",
    value: "7",
    detail: "дней перед оплатой",
    Icon: FileCheck2
  },
  {
    label: "Платежный контур",
    value: "demo",
    detail: "CloudPayments готовится",
    Icon: ShieldCheck
  },
  {
    label: "Тестовый платеж",
    value: "1 ₽",
    detail: "показан в интерфейсе",
    Icon: BadgeRussianRuble
  }
];

export function findProduct(code: string | null | undefined): Product | undefined {
  if (!code) {
    return undefined;
  }

  return products.find((product) => product.code === code);
}

export function formatRubles(value: number): string {
  return new Intl.NumberFormat("ru-RU").format(value) + " ₽";
}
