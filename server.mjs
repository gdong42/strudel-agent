import { createServer } from 'node:http';
import { readFile, stat, writeFile } from 'node:fs/promises';
import { watchFile } from 'node:fs';
import { extname, join, resolve } from 'node:path';

const root = resolve('.');
const trackPath = join(root, 'track.strudel.js');
const host = process.env.HOST || '127.0.0.1';
const port = Number(process.env.PORT || 8787);
const clients = new Set();
let lastWriteFromBrowser = 0;

const mimeTypes = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
};

function sendEvent(res, event, data) {
  res.write(`event: ${event}\n`);
  res.write(`data: ${JSON.stringify(data)}\n\n`);
}

async function readTrack() {
  return readFile(trackPath, 'utf8');
}

async function broadcastTrack() {
  const code = await readTrack();
  console.log(`Broadcasting track update to ${clients.size} client(s).`);
  for (const res of clients) {
    sendEvent(res, 'track', { code, updatedAt: Date.now() });
  }
}

watchFile(trackPath, { interval: 250 }, (current, previous) => {
  if (current.mtimeMs === previous.mtimeMs) {
    return;
  }
  if (Date.now() - lastWriteFromBrowser < 200) {
    return;
  }
  broadcastTrack().catch((error) => {
    for (const res of clients) {
      sendEvent(res, 'error', { message: error.message });
    }
  });
});

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url || '/', `http://${req.headers.host}`);

    if (url.pathname === '/track' && req.method === 'POST') {
      let body = '';
      req.setEncoding('utf8');
      for await (const chunk of req) {
        body += chunk;
        if (body.length > 500_000) {
          res.writeHead(413);
          res.end('Track is too large');
          return;
        }
      }

      const payload = JSON.parse(body);
      if (typeof payload.code !== 'string') {
        res.writeHead(400);
        res.end('Expected { "code": string }');
        return;
      }
      if (!payload.code.trim()) {
        res.writeHead(400);
        res.end('Refusing to write an empty track');
        return;
      }

      lastWriteFromBrowser = Date.now();
      await writeFile(trackPath, payload.code, 'utf8');
      res.writeHead(204);
      res.end();
      return;
    }

    if (url.pathname === '/events') {
      res.writeHead(200, {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache, no-transform',
        Connection: 'keep-alive',
      });
      clients.add(res);
      sendEvent(res, 'track', { code: await readTrack(), updatedAt: Date.now() });
      req.on('close', () => clients.delete(res));
      return;
    }

    const requestPath = url.pathname === '/' ? '/index.html' : url.pathname;
    const filePath = resolve(join(root, requestPath));
    if (!filePath.startsWith(root)) {
      res.writeHead(403);
      res.end('Forbidden');
      return;
    }

    const fileStat = await stat(filePath);
    if (!fileStat.isFile()) {
      res.writeHead(404);
      res.end('Not found');
      return;
    }

    res.writeHead(200, {
      'Content-Type': mimeTypes[extname(filePath)] || 'application/octet-stream',
      'Cache-Control': 'no-cache',
    });
    res.end(await readFile(filePath));
  } catch (error) {
    res.writeHead(error.code === 'ENOENT' ? 404 : 500);
    res.end(error.code === 'ENOENT' ? 'Not found' : error.message);
  }
});

server.listen(port, host, () => {
  console.log(`Strudel vibe server listening at http://${host}:${port}`);
  console.log(`Edit ${trackPath} to update the running pattern.`);
});
