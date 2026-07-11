import { cache } from "react";
import fs from "node:fs/promises";
import path from "node:path";
import legalManifest from "@/generated/legal-manifest.json";

export type LegalBlock =
  | {
      type: "heading";
      level: 2 | 3;
      text: string;
    }
  | {
      type: "paragraph";
      text: string;
    }
  | {
      type: "list";
      ordered: boolean;
      items: string[];
    }
  | {
      type: "table";
      headers: string[];
      rows: string[][];
    };

export type LegalDocument = {
  slug: LegalSlug;
  title: string;
  version: string;
  sourcePath: string;
  blocks: LegalBlock[];
};

export type LegalSlug =
  | "privacy"
  | "consent-personal-data"
  | "offer"
  | "cancellation"
  | "cookies"
  | "security";

type LegalDocumentMeta = {
  slug: LegalSlug;
  href: string;
  label: string;
  version: string;
  sourcePath: string;
};

const legalDocsRoot = path.resolve(process.cwd(), "../../docs/legal/ru");
const currentLegalVersion = "2026-07-11";

<<<<<<< HEAD:apps/web/src/features/legal/legal.ts
export const legalDocuments = Object.fromEntries(
  legalManifest.documents.map((document) => [
    document.slug,
    {
      slug: document.slug as LegalSlug,
      href: document.urlPath,
      label: document.title,
      version: document.version,
      sourcePath: `${document.version}/${document.file}`
    }
  ])
) as Record<LegalSlug, LegalDocumentMeta>;
=======
export const legalDocuments: Record<LegalSlug, LegalDocumentMeta> = {
  privacy: {
    slug: "privacy",
    href: "/ru/privacy",
    label: "Политика в отношении обработки персональных данных",
    version: currentLegalVersion,
    sourcePath: `${currentLegalVersion}/01-privacy-policy.md`
  },
  "consent-personal-data": {
    slug: "consent-personal-data",
    href: "/ru/consent-personal-data",
    label: "Согласие на обработку персональных данных",
    version: currentLegalVersion,
    sourcePath: `${currentLegalVersion}/02-consent-personal-data.md`
  },
  offer: {
    slug: "offer",
    href: "/ru/offer",
    label: "Публичная оферта",
    version: currentLegalVersion,
    sourcePath: `${currentLegalVersion}/03-offer.md`
  },
  cancellation: {
    slug: "cancellation",
    href: "/ru/cancellation",
    label: "Условия отмены подписки и возврата денежных средств",
    version: currentLegalVersion,
    sourcePath: `${currentLegalVersion}/04-cancellation-refund.md`
  },
  cookies: {
    slug: "cookies",
    href: "/ru/cookies",
    label: "Политика использования файлов cookie",
    version: currentLegalVersion,
    sourcePath: `${currentLegalVersion}/05-cookie-policy.md`
  },
  security: {
    slug: "security",
    href: "/ru/security",
    label: "Политика информационной безопасности",
    version: currentLegalVersion,
    sourcePath: `${currentLegalVersion}/06-security-policy.md`
  }
};
>>>>>>> 8468fa5 (ANY-91 / Visual refinements and document edits):apps/web/src/lib/legal.ts

export const legalLinks = Object.values(legalDocuments).map((document) => ({
  href: document.href,
  label: document.label
}));

function stripFrontmatter(markdown: string): string {
  if (!markdown.startsWith("---")) {
    return markdown;
  }

  const closingIndex = markdown.indexOf("\n---", 3);
  if (closingIndex === -1) {
    return markdown;
  }

  return markdown.slice(closingIndex + 4).trimStart();
}

function parseTableRow(line: string): string[] {
  return line
    .split("|")
    .map((cell) => cell.trim())
    .filter((cell, index, array) => {
      const isEdge = (index === 0 || index === array.length - 1) && cell === "";
      return !isEdge;
    });
}

function parseLegalMarkdown(markdown: string, slug: LegalSlug): LegalDocument {
  const source = stripFrontmatter(markdown).replace(/\r\n/g, "\n").trim();
  const lines = source.split("\n");
  const blocks: LegalBlock[] = [];
  let title = legalDocuments[slug].label;
  let index = 0;

  while (index < lines.length) {
    const line = lines[index].trim();

    if (!line) {
      index += 1;
      continue;
    }

    if (line.startsWith("# ")) {
      title = line.slice(2).trim();
      index += 1;
      continue;
    }

    if (line.startsWith("## ") || line.startsWith("### ")) {
      blocks.push({
        type: "heading",
        level: line.startsWith("### ") ? 3 : 2,
        text: line.replace(/^###?\s+/, "").trim()
      });
      index += 1;
      continue;
    }

    if (line.startsWith("|")) {
      const tableLines: string[] = [];
      while (index < lines.length && lines[index].trim().startsWith("|")) {
        tableLines.push(lines[index].trim());
        index += 1;
      }

      const [headerRow, separatorRow, ...rowLines] = tableLines;
      if (headerRow && separatorRow) {
        blocks.push({
          type: "table",
          headers: parseTableRow(headerRow),
          rows: rowLines.map(parseTableRow)
        });
        continue;
      }
    }

    if (/^-\s+/.test(line) || /^\d+\.\s+/.test(line)) {
      const ordered = /^\d+\.\s+/.test(line);
      const items: string[] = [];
      while (index < lines.length) {
        const currentLine = lines[index].trim();
        const sameListType = ordered
          ? /^\d+\.\s+/.test(currentLine)
          : /^-\s+/.test(currentLine);

        if (!sameListType) {
          break;
        }

        items.push(currentLine.replace(ordered ? /^\d+\.\s+/ : /^-\s+/, "").trim());
        index += 1;
      }

      blocks.push({ type: "list", ordered, items });
      continue;
    }

    const paragraphLines: string[] = [];
    while (index < lines.length) {
      const currentLine = lines[index].trim();
      if (
        !currentLine ||
        currentLine.startsWith("#") ||
        currentLine.startsWith("|") ||
        /^-\s+/.test(currentLine) ||
        /^\d+\.\s+/.test(currentLine)
      ) {
        break;
      }
      paragraphLines.push(currentLine);
      index += 1;
    }

    if (paragraphLines.length > 0) {
      blocks.push({
        type: "paragraph",
        text: paragraphLines.join(" ")
      });
      continue;
    }

    index += 1;
  }

  return {
    slug,
    title,
    version: legalDocuments[slug].version,
    sourcePath: legalDocuments[slug].sourcePath,
    blocks
  };
}

export const getLegalDocument = cache(async (slug: LegalSlug) => {
  const documentMeta = legalDocuments[slug];
  const filePath = path.join(legalDocsRoot, documentMeta.sourcePath);
  const source = await fs.readFile(filePath, "utf8");
  return parseLegalMarkdown(source, slug);
});
