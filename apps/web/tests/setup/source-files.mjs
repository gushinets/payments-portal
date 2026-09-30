import { readdir, stat } from "node:fs/promises";

export async function sourceFiles(directory) {
  const entries = await readdir(directory);
  const files = await Promise.all(
    entries.map(async (entry) => {
      const entryPath = `${directory}/${entry}`;
      const entryStat = await stat(entryPath);
      if (entryStat.isDirectory()) {
        return sourceFiles(entryPath);
      }
      return /\.(ts|tsx|js|jsx)$/.test(entryPath) ? [entryPath] : [];
    })
  );
  return files.flat();
}
