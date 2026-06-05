# Datacenter frontend

Next.js map UI and AI chat for datacenter site planning.

See the **[project README](../README.md)** for full setup, architecture, and **how AI coding tools (Cursor) were used** to build this.

## Quick start

```bash
npm install
# set OPENAI_API_KEY in .env
npm run dev
```

Requires the FastAPI backend in `../fiber_api` on port 8000.

## Key paths

| Path | Purpose |
|------|---------|
| `app/components/MapViewer.tsx` | Map, draw search, overlays, markers |
| `app/components/ChatSidebar.tsx` | Map-aware AI chat |
| `app/components/MarkdownContent.tsx` | Rendered chat markdown |
| `app/api/chat/route.ts` | Agentic LLM + tool loop |
| `lib/chat-tools.ts` | Tool definitions and execution |
| `lib/site-analysis.ts` | Compare, constraints, reweight helpers |
| `scripts/test-*.ts` | Unit and e2e tests |

## Scripts

```bash
npm run dev
npm test
npm run test:e2e
npm run build
```
