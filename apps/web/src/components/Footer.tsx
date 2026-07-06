import Image from "next/image";
import Link from "next/link";
import { paymentMethods, seller, supportEmail } from "@/lib/catalog";
import { legalLinks } from "@/lib/legal";

function PaymentMethodIcon({ code }: { code: string }) {
  if (code === "card") {
    return (
      <span className="payment-logo payment-logo-card">
        <svg aria-hidden="true" viewBox="0 0 64 40">
          <defs>
            <linearGradient id="cardGradient" x1="0%" x2="100%" y1="0%" y2="100%">
              <stop offset="0%" stopColor="#7c3aed" />
              <stop offset="45%" stopColor="#2563eb" />
              <stop offset="100%" stopColor="#06b6d4" />
            </linearGradient>
          </defs>
          <rect x="6" y="7" width="52" height="26" rx="7" fill="url(#cardGradient)" />
          <circle cx="23" cy="20" r="7" fill="#f59e0b" fillOpacity="0.95" />
          <circle cx="31" cy="20" r="7" fill="#f97316" fillOpacity="0.82" />
          <rect x="40" y="14" width="10" height="3" rx="1.5" fill="rgba(255,255,255,0.72)" />
          <rect x="12" y="26" width="14" height="3" rx="1.5" fill="rgba(255,255,255,0.58)" />
        </svg>
      </span>
    );
  }

  if (code === "sbp") {
    return (
      <span className="payment-logo payment-logo-sbp">
        <svg aria-hidden="true" viewBox="0 0 97 120">
          <path d="M0 26.12l14.532 25.975v15.844L.017 93.863 0 26.12z" fill="#5B57A2" />
          <path
            d="M55.797 42.643l13.617-8.346 27.868-.026-41.485 25.414V42.643z"
            fill="#D90751"
          />
          <path d="M55.72 25.967l.077 34.39-14.566-8.95V0l14.49 25.967z" fill="#FAB718" />
          <path d="M97.282 34.271l-27.869.026-13.693-8.33L41.231 0l56.05 34.271z" fill="#ED6F26" />
          <path d="M55.797 94.007V77.322l-14.566-8.78.008 51.458 14.558-25.993z" fill="#63B22F" />
          <path d="M69.38 85.737L14.531 52.095 0 26.12l97.223 59.583-27.844.034z" fill="#1487C9" />
          <path d="M41.24 120l14.556-25.993 13.583-8.27 27.843-.034L41.24 120z" fill="#017F36" />
          <path d="M.017 93.863l41.333-25.32-13.896-8.526-12.922 7.922L.017 93.863z" fill="#984995" />
        </svg>
      </span>
    );
  }

  if (code === "mir") {
    return (
      <span className="payment-logo payment-logo-mir">
        <Image
          alt=""
          src="/payment/mir-logo.svg"
          width={49}
          height={14}
          unoptimized
        />
      </span>
    );
  }

  if (code === "tpay") {
    return (
      <span className="payment-logo payment-logo-tpay">
        <svg aria-hidden="true" viewBox="0 0 64 40">
          <rect x="12" y="6" width="40" height="28" rx="10" className="payment-svg-warning" />
          <path d="M24 15h16v4h-6v10h-4V19h-6z" className="payment-svg-dark" />
        </svg>
      </span>
    );
  }

  return (
    <span className="payment-logo payment-logo-fallback">
      <svg aria-hidden="true" viewBox="0 0 64 40">
        <defs>
          <linearGradient id="mirGradientA" x1="0%" x2="100%" y1="50%" y2="50%">
            <stop offset="0%" stopColor="#00a651" />
            <stop offset="100%" stopColor="#00c389" />
          </linearGradient>
          <linearGradient id="mirGradientB" x1="0%" x2="100%" y1="50%" y2="50%">
            <stop offset="0%" stopColor="#1fb6ff" />
            <stop offset="100%" stopColor="#2563eb" />
          </linearGradient>
          <linearGradient id="mirGradientC" x1="0%" x2="100%" y1="50%" y2="50%">
            <stop offset="0%" stopColor="#f0b90b" />
            <stop offset="100%" stopColor="#8dc63f" />
          </linearGradient>
        </defs>
        <path d="M10 26V14h5l4.3 7.3L23.7 14H29v12h-4v-6.4L21 26h-3.3l-4.1-6.4V26z" fill="url(#mirGradientA)" />
        <path d="M31 26V14h5v4h4.6c2.9 0 4.8 1.6 4.8 4c0 2.4-1.9 4-4.8 4zm5-4h3.4c0.9 0 1.5-0.4 1.5-1.1c0-0.7-0.6-1.1-1.5-1.1H36z" fill="url(#mirGradientB)" />
        <path d="M47 26V14h7.5c4 0 6.5 2.3 6.5 6c0 3.7-2.5 6-6.5 6zm5-4h1.9c1.5 0 2.5-0.8 2.5-2c0-1.3-1-2-2.5-2H52z" fill="url(#mirGradientC)" />
      </svg>
    </span>
  );
}

export function Footer() {
  return (
    <footer className="footer">
      <div className="footer-inner">
        <div>
          <p className="footer-text">
            <strong>{seller.name}</strong>
            <br />
            ИНН: {seller.inn} · ОГРНИП: {seller.ogrnip}
            <br />
            Юридический адрес: {seller.address}
            <br />
            Email поддержки:{" "}
            <a className="inline-link" href={`mailto:${supportEmail}`}>
              {supportEmail}
            </a>
          </p>
          <div className="footer-links" aria-label="Юридические документы">
            {legalLinks.map((link) => (
              <Link href={link.href} key={link.href}>
                {link.label}
              </Link>
            ))}
          </div>
        </div>
        <div className="footer-payments">
          <p className="footer-text">
            Поддерживаемые способы оплаты
          </p>
          <div className="payment-list" aria-label="Способы оплаты">
            {paymentMethods.map((method) =>
              method.href ? (
                <a
                  className="payment-icon-link"
                  href={method.href}
                  key={method.code}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={method.label}
                  title={method.label}
                >
                  <PaymentMethodIcon code={method.code} />
                </a>
              ) : (
                <span
                  className="payment-icon-link"
                  key={method.code}
                  aria-label={method.label}
                  title={method.label}
                >
                  <PaymentMethodIcon code={method.code} />
                </span>
              )
            )}
          </div>
        </div>
      </div>
    </footer>
  );
}
