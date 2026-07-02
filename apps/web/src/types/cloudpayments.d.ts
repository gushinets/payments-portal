export {};

declare global {
  interface Window {
    cp?: {
      CloudPayments?: new (options: {
        language?: string;
      }) => {
        pay: (
          kind: "charge",
          options: {
            publicId: string;
            description: string;
            amount: number;
            currency: string;
            accountId?: string;
            email?: string;
          },
          callbacks?: {
            onSuccess?: (options?: unknown) => void;
            onFail?: (reason?: unknown, options?: unknown) => void;
            onComplete?: (paymentResult?: unknown, options?: unknown) => void;
          }
        ) => void;
      };
    };
  }
}
