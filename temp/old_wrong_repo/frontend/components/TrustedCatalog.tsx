// frontend/components/TrustedCatalog.tsx
//
// Secure declarative component renderer inspired by A2UI.
//
// The agent emits structured envelopes; this catalog renders them using only
// pre-approved React components. Arbitrary HTML, script tags, or unknown
// component names are rejected — a compromised agent cannot inject UI.
//
// A2UI v1.0 candidate envelope protocol support:
//   createSurface    — initialises a surface with a catalogId reference
//   updateComponents — renders one or more typed components onto a surface
//   updateDataModel  — updates surface-scoped data without re-rendering
//   deleteSurface    — tears down the surface
//   callFunction     — invokes a pre-registered catalog function
//   actionResponse   — resolves a pending surface action

import React, { useState } from 'react';

// ---------------------------------------------------------------------------
// A2UI v1.0 candidate envelope types
// ---------------------------------------------------------------------------

type A2UIVersion = 'v1.0';

interface A2UISurface {
  surfaceId: string;
  catalogId: string;   // URL of the trusted catalog manifest
}

interface A2UIComponent {
  id: string;
  component: string;   // must map to a key in TRUSTED_CATALOG
  child?: string | string[]; // references other component IDs
  [key: string]: unknown; // flat catalog-defined properties
}

type ActionResponsePayload = 
  | { value: unknown; error?: never }
  | { error: unknown; value?: never };

// Discriminated union: exactly one message key per envelope.
type A2UIEnvelope =
  | { version: A2UIVersion; createSurface: A2UISurface }
  | { version: A2UIVersion; updateComponents: { surfaceId: string; components: A2UIComponent[] } }
  | { version: A2UIVersion; updateDataModel: { surfaceId: string; path: string; value: unknown } }
  | { version: A2UIVersion; deleteSurface: { surfaceId: string } }
  | { version: A2UIVersion; functionCallId: string; wantResponse?: boolean; callFunction: { call: string; args: Record<string, unknown> } }
  | { version: A2UIVersion; actionId: string; actionResponse: ActionResponsePayload };

// ---------------------------------------------------------------------------
// Trusted component catalog — the only components agents may render.
// ---------------------------------------------------------------------------

const ResolutionCard: React.FC<any> = (props) => (
  <div className="resolution-card">
    <h3>{props.status}</h3>
    <p>{props.summary}</p>
    {props.followUpActions && (
      <ul>{(props.followUpActions as string[]).map((a, i) => <li key={i}>{a}</li>)}</ul>
    )}
  </div>
);

const EvidenceCard: React.FC<any> = (props) => (
  <div className="evidence-card">
    <strong>{props.query}</strong>
    <p>{props.answer}</p>
    {props.sources && (
      <ul>{(props.sources as string[]).map((s, i) => <li key={i}><a href={s}>{s}</a></li>)}</ul>
    )}
  </div>
);

const StatusChip: React.FC<any> = ({ status }) => (
  <span className={`status-chip status-${status}`}>{status}</span>
);

const MissingInfoForm: React.FC<any> = (props) => (
  <div className="missing-info">
    <p>Additional information needed:</p>
    <ul>{(props.fields as string[] ?? []).map((f: string, i: number) => <li key={i}>{f}</li>)}</ul>
  </div>
);

const ResearchTimeline: React.FC<any> = (props) => (
  <div className="timeline">
    {(props.items as any[] ?? []).map((item: any, i: number) => (
      <div key={i} className="timeline-item">{item.label}</div>
    ))}
  </div>
);

const TicketSummary: React.FC<any> = (props) => (
  <div className="ticket-summary">
    <h4>Ticket: {props.ticketId}</h4>
    <p>{props.description}</p>
  </div>
);

const TextFallback: React.FC<any> = (props) => (
  <pre className="text-fallback">{JSON.stringify(props, null, 2)}</pre>
);

const TRUSTED_CATALOG: Record<string, React.ComponentType<any>> = {
  ResolutionCard,
  EvidenceCard,
  StatusChip,
  MissingInfoForm,
  ResearchTimeline,
  TicketSummary,
};

// ---------------------------------------------------------------------------
// Surface state manager
// ---------------------------------------------------------------------------

interface SurfaceState {
  surfaceId: string;
  catalogId: string;
  components: A2UIComponent[];
  dataModel: Record<string, unknown>;
}

export function useA2UISurfaces() {
  const [surfaces, setSurfaces] = useState<Record<string, SurfaceState>>({});

  const handleEnvelope = (envelope: A2UIEnvelope) => {
    if (envelope.version !== 'v1.0') {
      console.warn('Unknown A2UI version', envelope);
      return;
    }

    if ('createSurface' in envelope) {
      setSurfaces((prev) => ({
        ...prev,
        [envelope.createSurface.surfaceId]: { 
          surfaceId: envelope.createSurface.surfaceId,
          catalogId: envelope.createSurface.catalogId,
          components: [], 
          dataModel: {} 
        },
      }));
    } else if ('updateComponents' in envelope) {
      const { surfaceId, components } = envelope.updateComponents;
      if (!surfaces[surfaceId]) {
        console.warn(`Cannot update components: surface ${surfaceId} has not been created with createSurface`);
        return;
      }
      
      // Ensure there is exactly one root component
      const hasRoot = components.some(c => c.id === 'root');
      if (!hasRoot) {
        console.warn('Protocol violation: no root component found');
      }

      setSurfaces((prev) => ({
        ...prev,
        [surfaceId]: { ...prev[surfaceId], components },
      }));
    } else if ('updateDataModel' in envelope) {
      const { surfaceId, path, value } = envelope.updateDataModel;
      if (!surfaces[surfaceId]) {
        console.warn(`Cannot update data model: surface ${surfaceId} has not been created with createSurface`);
        return;
      }
      setSurfaces((prev) => ({
        ...prev,
        [surfaceId]: { 
          ...prev[surfaceId], 
          dataModel: { ...prev[surfaceId].dataModel, [path]: value } 
        },
      }));
    } else if ('deleteSurface' in envelope) {
      const { surfaceId } = envelope.deleteSurface;
      setSurfaces((prev) => {
        const next = { ...prev };
        delete next[surfaceId];
        return next;
      });
    } else if ('callFunction' in envelope) {
      const { functionCallId, wantResponse, callFunction } = envelope;
      console.log(`Received callFunction request: ID=${functionCallId}, call=${callFunction.call}, args=`, callFunction.args);
    } else if ('actionResponse' in envelope) {
      const { actionId, actionResponse } = envelope;
      console.log(`Received actionResponse: ID=${actionId}, value=`, actionResponse.value, "error=", actionResponse.error);
    }
  };

  return {
    surfaces,
    handleEnvelope,
  };
}

function renderComponent(component: A2UIComponent) {
  const Component = TRUSTED_CATALOG[component.component];
  if (!Component) {
    return <TextFallback key={component.id} {...component} />;
  }

  const enhancedProps = { ...component };
  return <Component key={component.id} {...enhancedProps} />;
}

export function A2UISurfaceRenderer({ surface }: { surface: SurfaceState }) {
  return (
    <div className="a2ui-surface" data-surface-id={surface.surfaceId}>
      {surface.components.map(renderComponent)}
    </div>
  );
}
