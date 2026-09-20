import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join, normalize, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createApiHandler } from './api.mjs';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const dist = join(root, 'dist');
const port = Number(process.env.PORT || 8787);
const apiHandler = createApiHandler();

const contentTypes = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.woff2': 'font/woff2',
};

function serve(res, filePath) {
  return readFile(filePath).then((content) => {
    res.writeHead(200, { 'content-type': contentTypes[extname(filePath)] || 'application/octet-stream' });
    res.end(content);
  }).catch(() => false);
}

const server = createServer(async (req, res) => {
  if (req.url?.startsWith('/api/')) return apiHandler(req, res, () => { res.writeHead(404); res.end(); });
  const requestPath = decodeURIComponent(new URL(req.url || '/', 'http://localhost').pathname);
  const safePath = normalize(join(dist, requestPath === '/' ? 'index.html' : requestPath));
  if (!safePath.startsWith(dist)) { res.writeHead(400); res.end('Bad path'); return; }
  try {
    const info = await stat(safePath);
    if (info.isFile() && await serve(res, safePath)) return;
  } catch {}
  await serve(res, join(dist, 'index.html'));
});

server.listen(port, '127.0.0.1', () => console.log(`INSPIRA running at http://127.0.0.1:${port}`));
