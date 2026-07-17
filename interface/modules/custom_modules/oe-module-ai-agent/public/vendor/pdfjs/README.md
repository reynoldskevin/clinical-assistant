# Vendored pdf.js (pdfjs-dist)

Version: 4.7.76 (pinned in package.json devDependencies).
Files: `pdf.min.mjs` (ESM entry) + `pdf.worker.min.mjs` (worker).

Used by `public/agent-widget.js` to render an uploaded PDF's first page to an
image for the citation-source preview (T56g). Loaded lazily via dynamic import
only when a PDF is uploaded. Regenerate by copying from
`node_modules/pdfjs-dist/build/` after bumping the pinned version.
