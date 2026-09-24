/** Where a problem's card lives on the page, so a link can take the reader to it. */
export function issueAnchor(issueId: string): string {
  return `issue-${issueId}`
}
