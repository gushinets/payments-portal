// Match complete subscription/access nouns, never the adjective in
// "Нет доступных продуктов" (a valid empty technical catalog).
export const inventedSubscriptionState = /нет\s+(?:активн[а-яё]+\s+)?(?:подписки|подписок|подписка|подписку|доступа?)(?![а-яё])|(?:подписк[аи]|доступа?)\s+(?:нет|отсутству(?:ет|ют))(?![а-яё])|no\s+(?:active\s+)?(?:subscriptions?|access)\b/iu;
