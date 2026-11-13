// Click (or Enter/Space) on inline code copies it and shows a short "Copied!" popup.
// Styles live in custom.css under "Inline code: click to copy". A block scope rather than
// an IIFE: this file is a classic script, so top-level `const` would be page-global.
{
  const GAP_PX = 6; // between the code and the popup
  const SHOW_MS = 1100;
  const SELECTOR = "code[data-copyable]";

  // Inline code inside a link keeps the link's click.
  for (const element of document.querySelectorAll(".content code.literal")) {
    if (element.closest("a, pre")) continue;
    element.dataset.copyable = "";
    element.tabIndex = 0;
    element.title = "Click to copy";
  }

  const toast = document.createElement("div");
  toast.className = "inline-copy-toast";
  toast.setAttribute("role", "status");
  document.body.append(toast);
  let hideTimer = 0;

  const hide = () => {
    delete toast.dataset.shown;
  };

  const show = (element, text) => {
    const rect = element.getBoundingClientRect();
    toast.textContent = text;
    toast.style.left = `${rect.left + rect.width / 2}px`;
    // Measured after the text is set; sits above the code, or below it near the top edge.
    const above = rect.top - GAP_PX - toast.offsetHeight;
    toast.style.top = `${above >= 0 ? above : rect.bottom + GAP_PX}px`;
    toast.dataset.shown = "";
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hide, SHOW_MS);
  };

  const copy = async (element) => {
    // A drag-select stays a selection rather than a copy.
    if (String(getSelection() ?? "").length > 0) return;
    try {
      await navigator.clipboard.writeText(element.textContent.trim());
      show(element, "Copied!");
    } catch {
      show(element, "Copy failed");
    }
  };

  const copyable = (target) => (target instanceof Element ? target.closest(SELECTOR) : null);

  document.addEventListener("click", (event) => {
    const element = copyable(event.target);
    if (element) void copy(element);
  });
  document.addEventListener("keydown", (event) => {
    const element = copyable(event.target);
    if (!element || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    void copy(element);
  });
  // The popup is fixed-position; drop it rather than let it drift away on scroll.
  addEventListener("scroll", hide, { passive: true });
}
