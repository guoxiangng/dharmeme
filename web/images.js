// Where template images are served from. Relative = next to this page; to move them to a
// CDN, set an absolute URL here (the host must send CORS headers, or PNG export is blocked).
const IMAGE_BASE = "images/";

const cache = new Map();

// Resolves to the template's loaded image, or null if it could not be loaded (the
// renderer then draws a placeholder).
export function loadImage(template) {
  if (!cache.has(template.id)) {
    cache.set(
      template.id,
      new Promise((resolve) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => resolve(null);
        img.crossOrigin = "anonymous";
        img.src = `${IMAGE_BASE}${template.image}`;
      }),
    );
  }
  return cache.get(template.id);
}
