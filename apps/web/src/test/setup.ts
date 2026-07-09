import "@testing-library/jest-dom";

// jsdom does not implement scrollIntoView; stub it so components that scroll to
// an anchor on mount/update (e.g. ChatStream) can render in tests.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
