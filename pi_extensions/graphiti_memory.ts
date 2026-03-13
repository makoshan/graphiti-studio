import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";

const SEARCH_PARAMS = Type.Object({
  query: Type.String({ description: "Search query for the project knowledge graph." }),
  limit: Type.Optional(Type.Number({ minimum: 1, maximum: 20 })),
});

const CAPTURE_PARAMS = Type.Object({
  content: Type.String({ description: "Important information the user explicitly wants to remember." }),
});

function textBlocksFromResults(result: any) {
  const snippets = Array.isArray(result?.results) ? result.results : [];
  if (!snippets.length) {
    return [{ type: "text", text: "No relevant memories found." }];
  }
  return snippets.slice(0, 6).map((item: any) => ({
    type: "text",
    text: `[${item.channel}] ${item.snippet}`,
  }));
}

async function postJson(url: string, body: unknown) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`HTTP ${response.status}: ${text}`);
  }

  return response.json();
}

export default function graphitiMemory(pi: ExtensionAPI) {
  const backendUrl = process.env.GRAPHITI_STUDIO_BACKEND_URL;
  const projectId = process.env.GRAPHITI_STUDIO_PROJECT_ID;

  if (!backendUrl || !projectId) {
    throw new Error("GRAPHITI_STUDIO_BACKEND_URL and GRAPHITI_STUDIO_PROJECT_ID must be set.");
  }

  pi.registerTool({
    name: "memory_search",
    label: "Memory Search",
    description: "Search the current project's graph memories and raw text snippets.",
    promptSnippet: "Look up project knowledge before answering factual questions.",
    promptGuidelines: [
      "Use this tool for factual questions about the project.",
      "Prefer this tool before making claims about entities, places, or relations in the graph.",
    ],
    parameters: SEARCH_PARAMS,
    async execute(_toolCallId, params) {
      const result = await postJson(`${backendUrl}/api/memory/search`, {
        project_id: projectId,
        query: params.query,
        limit: params.limit ?? 10,
      });

      return {
        content: textBlocksFromResults(result),
        details: result,
      };
    },
  });

  pi.registerTool({
    name: "memory_capture",
    label: "Memory Capture",
    description: "Save user-approved information into the current project's memory store.",
    promptSnippet: "Store durable facts only when the user explicitly asks to remember them.",
    promptGuidelines: [
      "Only call this tool after a clear user instruction to remember or save something.",
    ],
    parameters: CAPTURE_PARAMS,
    async execute(_toolCallId, params) {
      const result = await postJson(`${backendUrl}/api/memory/capture`, {
        project_id: projectId,
        content: params.content,
        source: "chat",
      });

      return {
        content: [
          {
            type: "text",
            text: `Saved memory ${result.id} and queued extract job ${result.job_id}.`,
          },
        ],
        details: {
          saved: true,
          id: result.id,
          job_id: result.job_id,
          status: result.status,
          references: { nodes: [], edges: [] },
        },
      };
    },
  });
}
