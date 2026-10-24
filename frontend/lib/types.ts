import type { AgentOutput } from "./response-types";
export type Role = "coordinator" | "resident";
export type Incident = {
  id: string;
  title: string;
  category: string;
  severity: string;
  status: string;
  latitude: number;
  longitude: number;
  location: string;
  summary: string;
  version: number;
  created_at: string;
  assigned_to: string | null;
  reported_casualties: number | null;
  response_status: string;
};
export type Report = {
  id: string;
  category: string;
  description: string;
  location: string;
  status: string;
  observed_at: string;
  created_at: string;
  incident_id: string;
  source: string;
  reported_casualties: number | null;
  photo?: string;
};
export type Assessment = {
  summary: string;
  confidence: number;
  category: string;
  severity: string;
  contradictions: string[];
  missing_information: string[];
  recommended_actions: string[];
  evidence_report_ids: string[];
};
export type Finding = { id: string; run_id: string; assessment: Assessment };
export type Activity = {
  id: string;
  action: string;
  details: string;
  created_at: string;
};
export type Dossier = Incident & {
  reports: Report[];
  findings: Finding[];
  evidence: { id: string; text: string; source: string; uncertainty: string }[];
  history: Activity[];
};
export type Resource = {
  id: string;
  name: string;
  category: string;
  location: string;
  latitude: number;
  longitude: number;
  capacity: number;
  occupancy: number;
  accessible: boolean;
  pet_friendly: boolean;
  contact: string;
  confirmed_at: string;
  published: boolean;
  version: number;
};
export type PublicUpdate = {
  id: string;
  incident_id: string;
  title: string;
  body: string;
  audience: string;
  status: string;
  published_at: string | null;
  created_at: string;
  latitude: number;
  longitude: number;
  category: string;
  severity: string;
};
export type AgentRun = {
  id: string;
  incident_id: string;
  report_id: string;
  stage: string;
  status: string;
  attempts: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  input: Record<string, unknown>;
  output: AgentOutput | null;
  raw_response: Record<string, unknown> | null;
  plan_id: string | null;
  error: string | null;
};
export type Simulation = {
  running: boolean;
  cursor: number;
  speed: number;
  mode: string;
  worker_heartbeat?: string;
};
export type ResourceRequest = {
  id: string;
  incident_id: string;
  resource_id: string;
  quantity: number;
  status: string;
  rationale: string;
};
export type Answer = {
  answer: string;
  sources: { id: string; title: string; text: string; href: string }[];
};
