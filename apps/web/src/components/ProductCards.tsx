import Link from "next/link";
import { ArrowRight, CheckCircle2 } from "lucide-react";
import { formatRubles, products } from "@/lib/catalog";

export function ProductCards({ selectedCode }: { selectedCode?: string }) {
  return (
    <div className="tools-grid">
      {products.map((product) => {
        const Icon = product.Icon;
        const selected = selectedCode === product.code;

        return (
          <article
            className={`tool-card${selected ? " active" : ""}`}
            key={product.code}
          >
            <div className="tool-icon-wrap">
              <Icon size={22} aria-hidden="true" />
            </div>
            <span className="tool-tag">{product.type}</span>
            <h3>{product.name}</h3>
            <p className="muted" style={{ margin: "0 0 8px" }}>
              {product.tagline}
            </p>
            <p className="card-copy">{product.description}</p>
            <ul className="check-list">
              {product.valuePoints.map((point) => (
                <li key={point}>{point}</li>
              ))}
            </ul>
            <div className="tool-card-bottom">
              <div className="price-line">
                <strong>{formatRubles(product.plan.priceRub)}</strong>
                <span>/ месяц</span>
              </div>
              <div className="button-row" style={{ marginTop: 0 }}>
                <span className="badge badge-live">
                  <CheckCircle2 size={12} aria-hidden="true" />
                  {product.plan.trialDays} дней бесплатно
                </span>
                <span className="badge badge-running">
                  {product.freeLimit}
                </span>
              </div>
              <div className="button-row">
                <Link
                  className="btn-primary"
                  href={`/ru/auth-checkout?product=${product.code}`}
                >
                  Оформить <ArrowRight size={15} aria-hidden="true" />
                </Link>
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}
