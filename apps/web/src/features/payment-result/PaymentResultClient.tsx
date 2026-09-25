import Link from "next/link";
import { Clock3, ShieldCheck } from "lucide-react";

export function PaymentResultClient() {
  return (
    <section className="page-section compact">
      <div className="result-panel">
        <span className="badge badge-demo">
          <Clock3 size={12} aria-hidden="true" />
          Оплата недоступна
        </span>
        <h1 className="legal-title" style={{ marginTop: 14 }}>
          Здесь пока нет результата платежа
        </h1>
        <p className="hero-copy">
          Портал больше не обрабатывает прежний сценарий оплаты. Возврат в
          браузер не подтверждает покупку и не предоставляет доступ.
        </p>
        <div className="notice" role="status">
          <ShieldCheck size={16} aria-hidden="true" />
          Дождитесь запуска новой биллинговой системы перед оформлением покупки.
        </div>
        <div className="hero-actions">
          <Link className="btn-primary" href="/ru/auth-checkout">
            Войти в аккаунт
          </Link>
          <Link className="btn-secondary" href="/ru">
            На главную
          </Link>
        </div>
      </div>
    </section>
  );
}
