// Where the project lives and how to support it.
//
// Fill this in once the repository and the donation pages exist: the About window, the welcome
// tour and the README all point here. An entry with an empty address is simply not shown, so
// nothing in the app ever links to a page that does not exist.

export interface SupportLink {
  id: string;
  label: string;
  /** The page's address (https://…), or "" while there is none. */
  url: string;
}

export const PROJECT = {
  name: "CheapTrader",
  license: "MIT",
  /** The repository, e.g. "https://github.com/your-name/CheapTrader". */
  repo: "https://github.com/REDIN14/CheapTrader",
  /** Where problems are reported; the repository's issues page when this is empty. */
  issues: "",
  /** Where to donate, in the order they are shown. */
  support: [
    { id: "github", label: "GitHub Sponsors", url: "" },
    { id: "kofi", label: "Ko-fi", url: "" },
    { id: "liberapay", label: "Liberapay", url: "" },
    { id: "paypal", label: "PayPal", url: "" },
  ] as SupportLink[],
};

/** Only real web addresses are ever linked. */
export const isWebAddress = (url: string): boolean => /^https:\/\/[^\s/]+\.[^\s/]+/i.test(url);

/** The donation pages that are set up. */
export function supportLinks(project: Pick<typeof PROJECT, "support"> = PROJECT): SupportLink[] {
  return project.support.filter((s) => isWebAddress(s.url));
}

/** The address of the page for reporting problems, if the project has one. */
export function issuesUrl(project: Pick<typeof PROJECT, "repo" | "issues"> = PROJECT): string | null {
  if (isWebAddress(project.issues)) return project.issues;
  return isWebAddress(project.repo) ? `${project.repo.replace(/\/+$/, "")}/issues` : null;
}

/** The address of the licence text in the repository, if there is one. */
export function licenseUrl(project: Pick<typeof PROJECT, "repo"> = PROJECT): string | null {
  return isWebAddress(project.repo) ? `${project.repo.replace(/\/+$/, "")}/blob/main/LICENSE` : null;
}
