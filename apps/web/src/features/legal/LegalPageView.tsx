import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { Fragment, ReactNode } from "react";
import { LegalBlock, LegalDocument } from "./legal";

function renderInline(text: string): ReactNode[] {
  const result: ReactNode[] = [];
  const tokenPattern = /(\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g;
  let lastIndex = 0;
  let match = tokenPattern.exec(text);

  while (match) {
    const token = match[0];
    const matchIndex = match.index ?? 0;

    if (matchIndex > lastIndex) {
      result.push(text.slice(lastIndex, matchIndex));
    }

    if (token.startsWith("**")) {
      result.push(<strong key={`${matchIndex}-strong`}>{token.slice(2, -2)}</strong>);
    } else {
      const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (linkMatch) {
        const [, label, href] = linkMatch;
        const isInternal = href.startsWith("/");
        result.push(
          isInternal ? (
            <Link className="inline-link" href={href} key={`${matchIndex}-link`}>
              {label}
            </Link>
          ) : (
            <a
              className="inline-link"
              href={href}
              key={`${matchIndex}-link`}
              target="_blank"
              rel="noreferrer"
            >
              {label}
            </a>
          )
        );
      } else {
        result.push(token);
      }
    }

    lastIndex = matchIndex + token.length;
    match = tokenPattern.exec(text);
  }

  if (lastIndex < text.length) {
    result.push(text.slice(lastIndex));
  }

  return result;
}

function renderBlock(
  block: LegalBlock,
  index: number,
  tableAccessibilityLabel: string
) {
  if (block.type === "heading") {
    return block.level === 2 ? (
      <h2 key={index}>{block.text}</h2>
    ) : (
      <h3 className="legal-subtitle" key={index}>
        {block.text}
      </h3>
    );
  }

  if (block.type === "paragraph") {
    return <p key={index}>{renderInline(block.text)}</p>;
  }

  if (block.type === "list") {
    const ListTag = block.ordered ? "ol" : "ul";
    return (
      <ListTag className="legal-list" key={index}>
        {block.items.map((item) => (
          <li key={item}>{renderInline(item)}</li>
        ))}
      </ListTag>
    );
  }

  return (
    <div
      aria-label={tableAccessibilityLabel}
      className="legal-table-wrap"
      key={index}
      role="region"
      tabIndex={0}
    >
      <table className="legal-table">
        <thead>
          <tr>
            {block.headers.map((header) => (
              <th key={header}>{renderInline(header)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell) => (
                <td key={cell}>{renderInline(cell)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export async function LegalPageView({ page }: { page: LegalDocument }) {
  const t = await getTranslations("LegalPresentation");

  return (
    <section className="page-section compact" lang="ru">
      <div className="eyebrow">
        <span className="eyebrow-dot" />
        {t("eyebrow")}
      </div>
      <h1 className="legal-title">{page.title}</h1>
      <p className="hero-copy">
        {t("canonicalLanguageHelp")}
        <br />
        {t("versioningHelp")}
        <br className="mobile-only-break" />{" "}
        {t("revision", { version: page.version })}
      </p>

      <article className="legal-panel legal-document-panel" style={{ marginTop: 28 }}>
        {page.blocks.map((block, index) => (
          <Fragment key={`${page.slug}-${index}`}>
            {renderBlock(block, index, t("tableAccessibilityLabel"))}
          </Fragment>
        ))}
      </article>
    </section>
  );
}
