// jsdom lacks a few browser APIs antd relies on.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});
class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO;
// jsdom does not implement pseudo-element styles; antd only reads them for scrollbar sizing.
const realGetComputedStyle = window.getComputedStyle.bind(window);
window.getComputedStyle = (elt: Element) => realGetComputedStyle(elt);
