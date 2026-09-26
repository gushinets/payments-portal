import { ArrowRight } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { productPresentation } from "./catalog";

export function ProductOverview() {
  return (
    <>
      <div className="notice" role="status" style={{ marginBottom: 16 }}>
        Каталог тарифов и оформление покупок временно недоступны.
      </div>
      <div className="tools-grid">
        {Object.entries(productPresentation).map(([code, product]) => {
          const Icon = product.Icon;
          return (
            <article className="tool-card" key={code}>
              <div className="tool-icon-wrap">
                <Icon size={22} aria-hidden="true" />
              </div>
              <span className="tool-tag">{product.type}</span>
              <h3>{product.tagline}</h3>
              <p className="card-copy">{product.description}</p>
              <div className="tool-card-bottom">
                <span className="badge badge-demo">Информация о продукте</span>
              </div>
            </article>
          );
        })}
      </div>
      <div className="hero-actions">
        <Link className="btn-primary" href="/auth-checkout">
          Войти или зарегистрироваться
          <ArrowRight size={15} aria-hidden="true" />
        </Link>
      </div>
    </>
  );
}
