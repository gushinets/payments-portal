import { Clock3, ShieldCheck } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";

export async function PaymentResultClient() {
  const t = await getTranslations("PaymentResult");

  return (
    <section className="page-section compact">
      <div className="result-panel">
        <span className="badge badge-demo">
          <Clock3 size={12} aria-hidden="true" />
          {t("badge")}
        </span>
        <h1 className="legal-title" style={{ marginTop: 14 }}>
          {t("title")}
        </h1>
        <p className="hero-copy">{t("description")}</p>
        <div className="notice" role="status">
          <ShieldCheck size={16} aria-hidden="true" />
          {t("notice")}
        </div>
        <div className="hero-actions">
          <Link className="btn-primary" href="/auth-checkout">
            {t("accountAction")}
          </Link>
          <Link className="btn-secondary" href="/">
            {t("homeAction")}
          </Link>
        </div>
      </div>
    </section>
  );
}
