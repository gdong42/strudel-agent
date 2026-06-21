export interface TrackPayload {
  code: string;
  updatedAt: number;
}

export function connectTrackEvents(onTrack: (payload: TrackPayload) => void, onError: () => void): EventSource {
  const source = new EventSource('/events');

  source.addEventListener('track', (event) => {
    onTrack(JSON.parse(event.data) as TrackPayload);
  });

  source.addEventListener('error', () => {
    onError();
  });

  return source;
}

export async function fetchTrack(): Promise<TrackPayload> {
  const response = await fetch('/track');
  if (!response.ok) {
    throw new Error(`Failed to load track: ${response.status}`);
  }
  return response.json() as Promise<TrackPayload>;
}

export async function saveTrack(code: string): Promise<void> {
  const response = await fetch('/track', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Failed to save track: ${response.status}`);
  }
}
