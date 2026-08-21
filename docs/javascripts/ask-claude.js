/* "Ask Claude about this page" — injected next to each page's title.
 *
 * The hero button covers "I don't want to read any of this". This covers the more common case:
 * someone is ON a page, hits a term or a verdict they don't follow, and would rather ask than
 * read the rest of it.
 *
 * The prompt names THIS page first and the full-documentation file second, so the answer is
 * about what the reader is looking at while still having the wider context available. It also
 * tells Claude to say so if it cannot fetch the pages, rather than improvising a plausible
 * description of a tool it has never seen — the same rule this project applies to itself.
 *
 * Built with document.title / location.href at runtime, so it works on every page including
 * ones added later, and there is no per-page markup to forget to update.
 */
(function () {
  "use strict";

  var FULL = "/llms-full.txt";

  function buildPrompt(pageUrl, pageTitle, fullUrl) {
    return (
      "Read " + pageUrl + " — the \"" + pageTitle + "\" page from the documentation for Drift " +
      "Detector, a tool that finds third-party APIs a codebase calls which are being switched " +
      "off, down to file:line. For wider context the complete documentation is at " + fullUrl +
      ".\n\nThen answer my question about this page. If you cannot fetch those URLs, say so " +
      "plainly rather than guessing what the tool does.\n\nMy question: "
    );
  }

  function mount() {
    var article = document.querySelector("article.md-content__inner");
    if (!article || article.querySelector(".dd-ask--page")) return;

    var heading = article.querySelector("h1");
    if (!heading) return;                       // the hero page has its own button already
    if (document.querySelector(".dd-hero")) return;

    var fullUrl = location.origin + (document.body.dataset.mdBase || "") + FULL;
    // normalise: site_url may be served from a sub-path (GitHub Pages project sites are)
    var base = document.querySelector("link[rel=canonical]");
    if (base) {
      try {
        var u = new URL(base.href);
        var root = u.pathname.replace(/\/[^/]*\/?$/, "/");
        fullUrl = u.origin + root.replace(/\/[^/]*\/$/, "/") + "llms-full.txt";
      } catch (e) { /* fall through to the origin-relative guess */ }
    }

    var title = (document.title || "").split(" - ")[0].trim() || "this page";
    var href = "https://claude.ai/new?q=" +
      encodeURIComponent(buildPrompt(location.href, title, fullUrl));

    var a = document.createElement("a");
    a.className = "dd-ask dd-ask--page";
    a.href = href;
    a.target = "_blank";
    a.rel = "noopener";
    a.title = "Open Claude with this page as context";
    a.textContent = "Ask Claude about this page";
    heading.insertAdjacentElement("afterend", a);
  }

  if (document.readyState !== "loading") mount();
  else document.addEventListener("DOMContentLoaded", mount);
  // Material ships instant navigation: re-mount when it swaps the content in.
  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(mount);
  }
})();
