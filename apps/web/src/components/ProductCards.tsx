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
          <Link
            className={`tool-card${selected ? " active" : ""}`}
            href={`/ru/auth-checkout?product=${product.code}`}
            key={product.code}
          >
            <div className="tool-icon-wrap">
              <Icon size={22} aria-hidden="true" />
            </div>
            <span className="tool-tag">{product.type}</span>
            <h3>{product.name}</h3>
            <p className="card-copy">{product.description}</p>
            <div className="price-line">
              <strong>{formatRubles(product.plan.priceRub)}</strong>
              <span>/ месяц</span>
            </div>
            <span className="badge badge-live">
              <CheckCircle2 size={12} aria-hidden="true" />
              {product.plan.trialDays} дней trial
            </span>
            <div className="button-row">
              <span className="btn-secondary">
                Оформить <ArrowRight size={15} aria-hidden="true" />
              </span>
            </div>
          </Link>
        );
      })}
    </div>
  );
}
