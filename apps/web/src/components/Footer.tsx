import Link from "next/link";
import { legalLinks, paymentMethods, seller, supportEmail } from "@/lib/catalog";

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
        <div>
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
                  <span className="payment-icon-mark">{method.mark}</span>
                </a>
              ) : (
                <span
                  className="payment-icon-link"
                  key={method.code}
                  aria-label={method.label}
                  title={method.label}
                >
                  <span className="payment-icon-mark">{method.mark}</span>
                </span>
              )
            )}
          </div>
        </div>
      </div>
    </footer>
  );
}
