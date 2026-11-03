# TestAgent web

React 19 + Vite + Ant Design 6 + React Flow workbench. The production build goes to
`../src/testagent/web/` and is served by FastAPI at `/` (SPA fallback; `/api/*` stays JSON).

```powershell
npm ci --cache .npm-cache   # once
npm run build               # → ../src/testagent/web
npm test                    # vitest
npm run lint
```

Dev mode with hot reload: start the backend (`uv run testagent --no-browser`), then `npm run dev`,
open `http://localhost:5173/` and sign in with an account (create one once with
`uv run testagent user add <name> --admin`). Vite proxies `/api` to 127.0.0.1:8765.

API types: `uv run python ops/export_openapi.py` then `npm run gen:api` regenerates
`src/api/schema.d.ts` from the backend schema.
