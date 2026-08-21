export type CheckoutActionContract = {
  provider: string;
  experience: "widget" | "redirect" | "embedded";
  mode: string;
  public_identifier?: string | null;
  amount_minor: number;
  amount: number | string;
  currency: string;
  merchant_order_id: string;
  provider_invoice_id: string;
  account_id: string;
  description?: string | null;
  metadata?: Record<string, unknown>;
};

export type CheckoutIntentProductStateResponse = {
  product_code: string;
  plan_code?: string | null;
  plan_name?: string | null;
  invoice_id?: string | null;
  transaction_id?: string | null;
  status: "inactive" | "pending";
  starts_at?: string | null;
  expires_at?: string | null;
};

export type CheckoutIntentResponse = {
  status?: string;
  product_state: CheckoutIntentProductStateResponse;
  checkout: {
    amount_minor: number;
    amount: number;
    currency: string;
    action: CheckoutActionContract;
  };
};
