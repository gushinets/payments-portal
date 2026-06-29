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
            Планируемые способы оплаты через CloudPayments. Состав может быть
            скорректирован после подключения терминала.
          </p>
          <div className="payment-list" aria-label="Планируемые способы оплаты">
            {paymentMethods.map((method) => (
              <span className="payment-pill" key={method}>
                {method}
              </span>
            ))}
          </div>
        </div>
      </div>
    </footer>
  );
}
