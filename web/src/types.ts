export type Level = "low" | "medium" | "high";
export type DecisionStatus = "proposed" | "reassessed";

export interface IngestedDocument {
  file_name: string;
  source: string;
  document_type: string;
  location: string | null;
  ingested_at: string;
}

export interface Workspace {
  workspace_id: string;
  name: string;
  description: string;
  created_at: string;
  documents: IngestedDocument[];
  document_count: number;
  graph_built: boolean;
  knowledge_updated_at: string | null;
}

export interface Evidence {
  evidence_id: string;
  statement: string;
  source: string | null;
  relevance: Level;
}
export interface Claim {
  statement: string;
  supporting_evidence: string[];
}
export interface Assumption {
  statement: string;
  confidence: Level;
}
export interface Risk {
  statement: string;
  severity: Level;
  rationale: string;
}
export interface Alternative {
  name: string;
  description: string;
  advantages: string[];
  disadvantages: string[];
  evidence: string[];
}
export interface Recommendation {
  statement: string;
  rationale: string;
  confidence: Level;
}

export interface Decision {
  decision_id: string;
  workspace_id: string;
  session_id: string;
  question: string;
  status: DecisionStatus;
  created_at: string;
  recommendation: Recommendation;
  evidence: Evidence[];
  claims: Claim[];
  assumptions: Assumption[];
  risks: Risk[];
  alternatives: Alternative[];
  sources: string[];
  supersedes: string | null;
  changed_since_previous: string[];
}

export interface ProvenanceEvidence {
  evidence_id: string;
  statement: string;
  source: string | null;
  relevance: Level;
}
export interface ProvenanceClaim {
  statement: string;
  evidence: ProvenanceEvidence[];
  unresolved_evidence_ids: string[];
}
export interface DecisionProvenance {
  decision_id: string;
  workspace_id: string;
  question: string;
  recommendation: {
    statement: string;
    rationale: string;
    confidence: Level;
    claims: ProvenanceClaim[];
  };
  sources: string[];
  uncited_evidence_ids: string[];
}

export interface ValidationIssue {
  code: string;
  message: string;
  subject: string | null;
}
export interface ValidationResult {
  decision_id: string;
  valid: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
}

export interface DecisionFreshness {
  decision_id: string;
  workspace_id: string;
  decided_at: string;
  knowledge_updated_at: string | null;
  stale: boolean;
  documents_added_since: string[];
  summary: string;
}

export interface DecisionComparison {
  left_decision_id: string;
  right_decision_id: string;
  right_supersedes_left: boolean;
  recommendation_changed: boolean;
  left_recommendation: string;
  right_recommendation: string;
  confidence_changed: boolean;
  left_confidence: Level;
  right_confidence: Level;
  status_changed: boolean;
  left_status: string;
  right_status: string;
  added_evidence: string[];
  removed_evidence: string[];
  added_claims: string[];
  removed_claims: string[];
  added_assumptions: string[];
  removed_assumptions: string[];
  added_risks: string[];
  removed_risks: string[];
  added_alternatives: string[];
  removed_alternatives: string[];
  changed_since_previous: string[];
}

export interface IngestResult {
  workspace_id: string;
  documents_ingested: number;
  dataset: string;
  graph_built: boolean;
}

export interface ChatAnswer {
  answer: string;
  sources: string[];
  retrieval: {
    semantic_hits: number;
    graph_hits: number;
    memory_hits: number;
  };
}
