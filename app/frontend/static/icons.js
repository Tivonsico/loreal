const paths = {
  image: "M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5v-13Zm3 11 3.5-4 2.5 2.8 1.8-2.1 2.2 3.3H7Zm1.8-6.8a1.7 1.7 0 1 0 0-3.4 1.7 1.7 0 0 0 0 3.4Z",
  audio: "M9 6.8v10.4a3.1 3.1 0 1 1-1.5-2.65V5.9l9-1.9v10.2a3.1 3.1 0 1 1-1.5-2.65V7.75L9 9v-2.2Z",
  video: "M4 6.5A1.5 1.5 0 0 1 5.5 5h9A1.5 1.5 0 0 1 16 6.5v2.2l4-2.2v11l-4-2.2v2.2a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 4 17.5v-11Z",
  file: "M6 3h8l4 4v14H6V3Zm8 1.8V8h3.2L14 4.8ZM9 12h6v1.5H9V12Zm0 3.5h6V17H9v-1.5Z",
};

export function createIcon(name, size = 18) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", paths[name] || paths.file);
  path.setAttribute("fill", "currentColor");
  svg.append(path);
  return svg;
}
