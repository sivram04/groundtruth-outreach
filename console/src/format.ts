/** A link that opens the founder's Gmail searched for one address, in the right account. */
export function gmailSearch(address: string, account: string): string {
  const who = account ? `?authuser=${encodeURIComponent(account).replace(/%40/g, "@")}` : "";
  return `https://mail.google.com/mail/u/${who}#search/${encodeURIComponent(address).replace(/%40/g, "@")}`;
}

/** The address itself when it is an http(s) link, else "". The server already checks this;
 *  a cell reading "javascript:..." must never become a link, so the page checks again. */
export function safeHref(url: string): string {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? url : "";
  } catch {
    return "";
  }
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}
