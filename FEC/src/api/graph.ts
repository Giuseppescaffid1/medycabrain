import { apiClient } from "./client";

export interface GraphNode {
  id: string;
  group: "hub" | "theme" | "reel" | "blog" | "opportunity" | "custom";
  label: string;
  sub: string;
  parent: string;
  owner: "owned" | "competitor" | "opportunity" | "pipeline" | string;
  detail: string;
  url: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  rel: string;
  kind: "structure" | "flow";
}

export interface GraphPayload {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export async function fetchGraph(): Promise<GraphPayload> {
  const { data } = await apiClient.get<GraphPayload>("/second-brain/graph/");
  return data;
}
