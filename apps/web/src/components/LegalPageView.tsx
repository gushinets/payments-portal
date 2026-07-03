import { LegalPage } from "@/lib/legal";

export function LegalPageView({ page }: { page: LegalPage }) {
  return (
    <section className="page-section compact">
      <div className="eyebrow">
        <span className="eyebrow-dot" />
        Юридический документ
      </div>
      <h1 className="legal-title">{page.title}</h1>
      {page.intro ? <p className="hero-copy">{page.intro}</p> : null}

      <div className="legal-grid" style={{ marginTop: 28 }}>
        {page.sections.map((section) => (
          <article className="legal-panel" key={section.title}>
            <h2>{section.title}</h2>
            {section.body.map((paragraph) => (
              <p key={paragraph}>{paragraph}</p>
            ))}
          </article>
        ))}
      </div>
    </section>
  );
}
